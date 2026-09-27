<script setup lang="ts">
type Identity = { email: string; name: string; role: string }
type ChatMessage = { id: string; role: string; body: string; metadata?: Record<string, unknown> }
type PendingAction = { id: string; type: string; status: string; payload: Record<string, unknown>; version: number }

const config = useRuntimeConfig()
const api = config.public.apiBase as string
const identities = ref<Identity[]>([])
const selected = ref('ava.customer@northstar.test')
const me = ref<{ role: string; name?: string } | null>(null)
const conversationId = ref<string | null>(null)
const messages = ref<ChatMessage[]>([])
const actions = ref<PendingAction[]>([])
const input = ref('Where is order NS-1042?')
const waiting = ref(false)
const error = ref('')
const activePanel = ref<'chat' | 'operations' | 'approvals' | 'tickets' | 'audit'>('chat')
const metrics = ref<Record<string, unknown> | null>(null)
const approvals = ref<Record<string, unknown>[]>([])
const tickets = ref<Record<string, unknown>[]>([])
const audit = ref<Record<string, unknown>[]>([])

const headers = computed(() => ({ 'X-Demo-Identity': selected.value }))
const isStaff = computed(() => Boolean(me.value && me.value.role !== 'customer'))
const isSupervisor = computed(() => me.value?.role === 'supervisor' || me.value?.role === 'administrator')

async function request<T>(path: string, options: Record<string, unknown> = {}) {
  return await $fetch<T>(`${api}${path}`, { ...options, headers: { ...headers.value, ...(options.headers as object || {}) } })
}

async function loadConversation() {
  if (!conversationId.value) return
  const data = await request<{ messages: ChatMessage[]; pending_actions: PendingAction[] }>(`/conversations/${conversationId.value}`)
  messages.value = data.messages
  actions.value = data.pending_actions
}

async function loadOps() {
  if (!isStaff.value) return
  metrics.value = await request('/metrics')
  tickets.value = await request('/tickets')
  audit.value = isSupervisor.value ? await request('/audit') : []
  approvals.value = isSupervisor.value ? await request('/approvals') : []
}

async function chooseIdentity() {
  error.value = ''; me.value = await request('/me')
  conversationId.value = null; messages.value = []; actions.value = []
  if (me.value.role === 'customer') {
    const list = await request<{ id: string }[]>('/conversations')
    if (list[0]) conversationId.value = list[0].id
    else conversationId.value = (await request<{ id: string }>('/conversations', { method: 'POST', body: {} })).id
    await loadConversation()
  } else await loadOps()
}

async function send() {
  if (!input.value.trim() || !conversationId.value) return
  const body = input.value; input.value = ''; waiting.value = true; error.value = ''
  try {
    const submitted = await request<{ turn_id: string }>(`/conversations/${conversationId.value}/messages`, {
      method: 'POST', body: { body }, headers: { 'Idempotency-Key': crypto.randomUUID() }
    })
    messages.value.push({ id: submitted.turn_id, role: 'user', body })
    for (let tries = 0; tries < 20; tries++) {
      await new Promise(resolve => setTimeout(resolve, Math.min(350 + tries * 100, 1200)))
      const turn = await request<{ status: string }>(`/turns/${submitted.turn_id}`)
      if (turn.status === 'completed' || turn.status === 'failed') { await loadConversation(); break }
    }
  } catch (cause: unknown) { error.value = cause instanceof Error ? cause.message : 'Message could not be sent.' }
  finally { waiting.value = false }
}

async function confirm(action: PendingAction) {
  await request(`/actions/${action.id}/confirm`, { method: 'POST', body: { version: action.version } })
  await loadConversation()
}

async function decide(id: string, decision: 'approve' | 'reject') {
  await request(`/approvals/${id}/${decision}`, { method: 'POST', body: { reason: decision === 'approve' ? 'Policy checks passed.' : 'Insufficient evidence.' } })
  await loadOps()
}

onMounted(async () => {
  identities.value = await $fetch<Identity[]>(`${api}/demo-identities`)
  await chooseIdentity()
})
</script>

<template>
  <main class="min-h-screen bg-slate-50 text-slate-900">
    <header class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex max-w-7xl items-center justify-between gap-4 px-5 py-4">
        <div><p class="text-lg font-bold tracking-tight text-indigo-700">ResolveAI</p><p class="text-xs text-slate-500">Safe support operations · synthetic demo data</p></div>
        <label class="flex items-center gap-2 text-sm"><span class="hidden text-slate-500 sm:inline">Demo identity</span><select v-model="selected" class="input w-72" @change="chooseIdentity"><option v-for="identity in identities" :key="identity.email" :value="identity.email">{{ identity.name }} — {{ identity.role }}</option></select></label>
      </div>
    </header>
    <div class="mx-auto grid max-w-7xl gap-5 px-5 py-6 lg:grid-cols-[190px_1fr]">
      <aside class="card h-fit p-3"><p class="label px-2 py-2">Workspace</p><button class="w-full rounded-lg px-3 py-2 text-left text-sm" :class="activePanel === 'chat' ? 'bg-indigo-50 text-indigo-700' : ''" @click="activePanel = 'chat'">Customer support</button><template v-if="isStaff"><button class="w-full rounded-lg px-3 py-2 text-left text-sm" :class="activePanel === 'operations' ? 'bg-indigo-50 text-indigo-700' : ''" @click="activePanel = 'operations'; loadOps()">Operations</button><button class="w-full rounded-lg px-3 py-2 text-left text-sm" :class="activePanel === 'tickets' ? 'bg-indigo-50 text-indigo-700' : ''" @click="activePanel = 'tickets'; loadOps()">Tickets</button><button v-if="isSupervisor" class="w-full rounded-lg px-3 py-2 text-left text-sm" :class="activePanel === 'approvals' ? 'bg-indigo-50 text-indigo-700' : ''" @click="activePanel = 'approvals'; loadOps()">Approvals</button><button v-if="isSupervisor" class="w-full rounded-lg px-3 py-2 text-left text-sm" :class="activePanel === 'audit' ? 'bg-indigo-50 text-indigo-700' : ''" @click="activePanel = 'audit'; loadOps()">Audit</button></template></aside>
      <section v-if="activePanel === 'chat'" class="card flex min-h-[650px] flex-col overflow-hidden">
        <div class="border-b border-slate-200 px-6 py-4"><p class="font-semibold">Customer support</p><p class="text-sm text-slate-500">{{ me?.role === 'customer' ? 'Demo AI uses controlled database actions.' : 'Switch to a customer identity to send a support request.' }}</p></div>
        <div class="flex-1 space-y-4 overflow-y-auto bg-slate-50 p-6"><div v-for="message in messages" :key="message.id" class="max-w-xl rounded-2xl px-4 py-3 text-sm" :class="message.role === 'user' ? 'ml-auto bg-indigo-600 text-white' : 'bg-white shadow-sm'">{{ message.body }}</div><div v-if="waiting" class="text-sm text-slate-500">Checking your request…</div><article v-for="action in actions" :key="action.id" class="max-w-xl rounded-xl border border-amber-200 bg-amber-50 p-4"><p class="font-semibold text-amber-900">{{ action.type === 'refund_review' ? 'Refund review' : 'Support ticket' }}</p><p class="mt-1 text-sm text-amber-800">{{ action.type === 'refund_review' ? `${action.payload.order_reference}: $${Number(action.payload.amount_minor)/100} requires supervisor approval.` : String(action.payload.subject) }}</p><button class="btn-primary mt-3" @click="confirm(action)">Confirm request</button></article><p v-if="!messages.length" class="text-sm text-slate-500">Ask about an order, demo policy, refund, ticket, or human help.</p></div>
        <form class="border-t border-slate-200 p-4" @submit.prevent="send"><p v-if="error" class="mb-2 text-sm text-red-700">{{ error }}</p><div class="flex gap-2"><input v-model="input" class="input" :disabled="me?.role !== 'customer' || waiting" placeholder="Ask about your order…"><button class="btn-primary" :disabled="me?.role !== 'customer' || waiting">Send</button></div></form>
      </section>
      <section v-else-if="activePanel === 'operations'" class="space-y-5"><div><p class="text-2xl font-bold">Operations overview</p><p class="text-sm text-slate-500">Live counts from the demo database. Cloud telemetry is intentionally unavailable locally.</p></div><div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><div v-for="(value, name) in metrics" :key="String(name)" class="card p-5"><p class="label">{{ String(name).replaceAll('_', ' ') }}</p><p class="mt-2 text-2xl font-bold">{{ value }}</p></div></div></section>
      <section v-else-if="activePanel === 'approvals'" class="space-y-4"><div><p class="text-2xl font-bold">Approval queue</p><p class="text-sm text-slate-500">Only a supervisor can authorize sandbox refunds.</p></div><article v-for="item in approvals" :key="String(item.id)" class="card p-5"><p class="font-semibold">{{ item.type }}</p><pre class="mt-2 overflow-auto rounded bg-slate-50 p-3 text-xs">{{ item.payload }}</pre><div class="mt-3 flex gap-2"><button class="btn-primary" @click="decide(String(item.id), 'approve')">Approve sandbox refund</button><button class="btn-secondary" @click="decide(String(item.id), 'reject')">Reject</button></div></article><p v-if="!approvals.length" class="text-sm text-slate-500">No pending approvals.</p></section>
      <section v-else-if="activePanel === 'tickets'" class="space-y-4"><div><p class="text-2xl font-bold">Tickets</p><p class="text-sm text-slate-500">Queue-visible customer requests.</p></div><article v-for="ticket in tickets" :key="String(ticket.id)" class="card flex items-center justify-between p-4"><div><p class="font-semibold">{{ ticket.subject }}</p><p class="text-sm text-slate-500">{{ ticket.priority }} · {{ ticket.status }}</p></div><span class="rounded-full bg-slate-100 px-3 py-1 text-xs">{{ ticket.status }}</span></article></section>
      <section v-else class="space-y-4"><div><p class="text-2xl font-bold">Audit events</p><p class="text-sm text-slate-500">Sanitized operational history.</p></div><article v-for="event in audit" :key="String(event.created_at)" class="card p-4"><p class="font-semibold">{{ event.action }}</p><p class="text-sm text-slate-500">{{ event.resource_type }} · {{ event.result }}</p></article></section>
    </div>
  </main>
</template>
