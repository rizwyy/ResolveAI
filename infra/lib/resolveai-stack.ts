import * as path from 'node:path'
import * as cdk from 'aws-cdk-lib'
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2'
import * as integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations'
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront'
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins'
import * as ec2 from 'aws-cdk-lib/aws-ec2'
import * as ecrAssets from 'aws-cdk-lib/aws-ecr-assets'
import * as events from 'aws-cdk-lib/aws-events'
import * as targets from 'aws-cdk-lib/aws-events-targets'
import * as iam from 'aws-cdk-lib/aws-iam'
import * as lambda from 'aws-cdk-lib/aws-lambda'
import * as lambdaEvents from 'aws-cdk-lib/aws-lambda-event-sources'
import * as rds from 'aws-cdk-lib/aws-rds'
import * as s3 from 'aws-cdk-lib/aws-s3'
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager'
import * as sqs from 'aws-cdk-lib/aws-sqs'
import { Construct } from 'constructs'

export class ResolveAiStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props)
    const vpc = new ec2.Vpc(this, 'Vpc', { maxAzs: 2, natGateways: 1 })
    const dbSecret = new secretsmanager.Secret(this, 'DatabaseSecret', { generateSecretString: { secretStringTemplate: JSON.stringify({ username: 'resolveai' }), generateStringKey: 'password', excludePunctuation: true } })
    const database = new rds.DatabaseInstance(this, 'Database', { vpc, engine: rds.DatabaseInstanceEngine.postgres({ version: rds.PostgresEngineVersion.VER_16 }), credentials: rds.Credentials.fromSecret(dbSecret), allocatedStorage: 20, maxAllocatedStorage: 100, multiAz: false, deletionProtection: true, backupRetention: cdk.Duration.days(7), publiclyAccessible: false })
    const queue = new sqs.Queue(this, 'TurnQueue', { visibilityTimeout: cdk.Duration.seconds(120), deadLetterQueue: { queue: new sqs.Queue(this, 'TurnDlq', { retentionPeriod: cdk.Duration.days(14) }), maxReceiveCount: 3 } })
    const apiAsset = new ecrAssets.DockerImageAsset(this, 'ApiImage', { directory: path.join(__dirname, '../../apps/api') })
    const commonEnvironment = { APP_ENV: 'cloud', AUTH_PROVIDER: 'cognito', AI_PROVIDER: 'bedrock', DATABASE_SECRET_ARN: dbSecret.secretArn, TURN_QUEUE_URL: queue.queueUrl }
    const fn = new lambda.DockerImageFunction(this, 'Api', { code: lambda.DockerImageCode.fromEcr(apiAsset.repository, { tagOrDigest: apiAsset.imageTag }), vpc, timeout: cdk.Duration.seconds(29), memorySize: 1024, reservedConcurrentExecutions: 10, environment: commonEnvironment, tracing: lambda.Tracing.ACTIVE })
    database.connections.allowDefaultPortFrom(fn, 'API to PostgreSQL')
    dbSecret.grantRead(fn); queue.grantSendMessages(fn)
    fn.addToRolePolicy(new iam.PolicyStatement({ actions: ['bedrock:Converse'], resources: ['*'] })) // narrow to a selected model/inference profile before deploy
    const worker = new lambda.DockerImageFunction(this, 'Worker', { code: lambda.DockerImageCode.fromEcr(apiAsset.repository, { tagOrDigest: apiAsset.imageTag }), vpc, timeout: cdk.Duration.seconds(120), memorySize: 1024, reservedConcurrentExecutions: 5, environment: commonEnvironment })
    database.connections.allowDefaultPortFrom(worker); dbSecret.grantRead(worker); queue.grantConsumeMessages(worker)
    worker.addEventSource(new lambdaEvents.SqsEventSource(queue, { batchSize: 5, reportBatchItemFailures: true }))
    new events.Rule(this, 'OutboxRecovery', { schedule: events.Schedule.rate(cdk.Duration.minutes(5)), targets: [new targets.LambdaFunction(worker)] })
    const httpApi = new apigwv2.HttpApi(this, 'HttpApi', { corsPreflight: { allowHeaders: ['Content-Type', 'Idempotency-Key'], allowMethods: [apigwv2.CorsHttpMethod.ANY], allowOrigins: ['https://REPLACE_BEFORE_DEPLOYMENT.example'] } })
    httpApi.addRoutes({ path: '/{proxy+}', methods: [apigwv2.HttpMethod.ANY], integration: new integrations.HttpLambdaIntegration('ApiIntegration', fn) })
    const site = new s3.Bucket(this, 'WebAssets', { blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, encryption: s3.BucketEncryption.S3_MANAGED, enforceSSL: true, autoDeleteObjects: false, removalPolicy: cdk.RemovalPolicy.RETAIN })
    const distribution = new cloudfront.Distribution(this, 'WebDistribution', { defaultBehavior: { origin: origins.S3BucketOrigin.withOriginAccessControl(site) }, defaultRootObject: 'index.html', errorResponses: [{ httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html' }, { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html' }] })
    new cdk.CfnOutput(this, 'ApiUrl', { value: httpApi.apiEndpoint })
    new cdk.CfnOutput(this, 'WebUrl', { value: `https://${distribution.domainName}` })
  }
}
