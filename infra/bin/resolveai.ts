#!/usr/bin/env node
import 'source-map-support/register'
import * as cdk from 'aws-cdk-lib'
import { ResolveAiStack } from '../lib/resolveai-stack'

const app = new cdk.App()
new ResolveAiStack(app, 'ResolveAiStack', { env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION } })
