<script lang="ts">
  import { onMount } from 'svelte';
  import {
    formatDate,
    formatPhone,
    getConversation,
    getConversations,
    PIPELINE_NAMES,
    type Conversation,
    type ConversationSummary,
    type Message,
  } from '../api';

  interface Props {
    selectedId: number | null;
    initialQuery: string;
  }

  let { selectedId, initialQuery }: Props = $props();

  const LIST_REFRESH_MS = 5000;
  const LIVE_REFRESH_MS = 2000;

  let conversations = $state<ConversationSummary[]>([]);
  let loaded = $state(false);
  let listError = $state('');
  let query = $state('');

  let detail = $state<Conversation | null>(null);
  let detailError = $state('');

  // A link from the customers section fills the search
  $effect(() => {
    query = initialQuery;
  });

  let filtered = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (!q) return conversations;
    const digits = q.replace(/\D/g, '');
    return conversations.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.preview.toLowerCase().includes(q) ||
        (digits && c.phone.includes(digits)),
    );
  });

  const TOOL_LABELS: Record<string, string> = {
    save_customer_name: 'Saved name',
    save_delivery_address: 'Checked address',
    add_to_order: 'Added to order',
    set_payment_method: 'Set payment',
    save_order_detail: 'Saved answer',
    save_phone_number: 'Saved phone',
    send_otp: 'Sent OTP',
    verify_otp: 'Checked OTP',
    cancel_order: 'Cancelled order',
    search_knowledge: 'Searched menu and FAQ',
  };

  async function loadList() {
    try {
      conversations = await getConversations();
      listError = '';
    } catch (e) {
      listError = `Can't load conversations. ${(e as Error).message}`;
    } finally {
      loaded = true;
    }
  }

  async function loadDetail(id: number) {
    try {
      const next = await getConversation(id);
      if (selectedId === id) {
        detail = next;
        detailError = '';
      }
    } catch (e) {
      if (selectedId === id) detailError = (e as Error).message;
    }
  }

  // Load the transcript when the selection changes, and keep a live one fresh
  $effect(() => {
    const id = selectedId;
    detail = null;
    detailError = '';
    if (id === null) return;
    loadDetail(id);
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible' && detail?.id === id && !detail.ended_at) {
        loadDetail(id);
      }
    }, LIVE_REFRESH_MS);
    return () => clearInterval(timer);
  });

  onMount(() => {
    loadList();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') loadList();
    }, LIST_REFRESH_MS);
    return () => clearInterval(timer);
  });

  function whoName(c: { name: string }): string {
    return c.name || 'Unknown caller';
  }

  function listTime(seconds: number): string {
    const date = new Date(seconds * 1000);
    if (date.toDateString() === new Date().toDateString()) {
      return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    }
    return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }

  function duration(c: Conversation): string {
    const seconds = Math.max(0, Math.round((c.ended_at ?? Date.now() / 1000) - c.started_at));
    return seconds < 60 ? `${seconds} s` : `${Math.round(seconds / 60)} min`;
  }

  function toolSummary(m: Message): string {
    const values = Object.values(m.tool_args ?? {}).map(String).join(', ');
    const label = TOOL_LABELS[m.tool_name] ?? m.tool_name;
    return values ? `${label}: ${values}` : label;
  }

  // A sender label shows when the speaker changes; tool rows don't count
  function showSender(messages: Message[], index: number): boolean {
    const role = messages[index].role;
    for (let i = index - 1; i >= 0; i--) {
      if (messages[i].role !== 'tool') return messages[i].role !== role;
    }
    return true;
  }
</script>

{#snippet status(c: { outcome: string; ended_at: number | null })}
  {#if !c.ended_at}
    <span class="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-success">
      <span class="w-2 h-2 rounded-full bg-success animate-pulse" aria-hidden="true"></span>
      Live
    </span>
  {:else if c.outcome === 'confirmed'}
    <span class="text-[12.5px] font-semibold text-success">✓ Ordered</span>
  {:else if c.outcome === 'cancelled'}
    <span class="text-[12.5px] font-semibold text-danger">✕ Cancelled</span>
  {:else}
    <span class="text-[12.5px] text-gray-400">No order</span>
  {/if}
{/snippet}

<div class="lg:grid lg:grid-cols-[minmax(280px,360px)_1fr] lg:gap-6 lg:items-start">
  <!-- List -->
  <div class={selectedId !== null ? 'hidden lg:block' : ''}>
    <input
      bind:value={query}
      type="search"
      placeholder="Search by name, phone or words"
      aria-label="Search conversations"
      class="w-full min-h-9 mb-3 px-4 rounded-xl bg-gray-200/70 text-[14.5px] text-gray-900
             placeholder:text-gray-400 border-none"
    />

    <div
      class="bg-white rounded-2xl border border-gray-200 overflow-hidden
             lg:max-h-[calc(100vh-190px)] lg:overflow-y-auto"
    >
      {#if listError}
        <p class="px-5 py-6 text-[13.5px] text-danger" role="alert">{listError}</p>
      {:else if !loaded}
        <p class="px-5 py-6 text-[13.5px] text-gray-400">Loading…</p>
      {:else if conversations.length === 0}
        <div class="px-5 py-10 text-center">
          <p class="text-[14.5px] font-semibold">No conversations yet</p>
          <p class="mt-1 text-[13.5px] text-gray-500">
            Each call to the agent shows up here as soon as the customer speaks.
          </p>
        </div>
      {:else if filtered.length === 0}
        <p class="px-5 py-6 text-[13.5px] text-gray-500">No conversation matches “{query}”.</p>
      {:else}
        <ul>
          {#each filtered as c (c.id)}
            {@const current = c.id === selectedId}
            <li class="border-t border-gray-200 first:border-t-0">
              <a
                href="#conversations/{c.id}"
                aria-current={current ? 'true' : undefined}
                class="flex gap-3 px-4 py-3 transition-colors
                       {current ? 'bg-accent-soft' : 'hover:bg-gray-100'}"
              >
                <span
                  class="w-10 h-10 shrink-0 rounded-full bg-gray-100 text-gray-600
                         flex items-center justify-center text-[14.5px] font-semibold"
                  aria-hidden="true"
                >
                  {c.name ? c.name.charAt(0).toUpperCase() : '?'}
                </span>
                <span class="flex-1 min-w-0">
                  <span class="flex items-baseline justify-between gap-2">
                    <span class="text-[14.5px] font-medium truncate">{whoName(c)}</span>
                    <span class="text-[12.5px] text-gray-400 shrink-0">{listTime(c.started_at)}</span>
                  </span>
                  <span class="block text-[13.5px] text-gray-500 truncate">
                    {c.preview || 'No words yet'}
                  </span>
                  <span class="flex items-center gap-1.5 mt-0.5">
                    {@render status(c)}
                    <span class="text-[12.5px] text-gray-400" aria-hidden="true">·</span>
                    <span class="text-[12.5px] text-gray-400">{PIPELINE_NAMES[c.channel]}</span>
                  </span>
                </span>
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </div>

  <!-- Transcript -->
  <div class={selectedId === null ? 'hidden lg:block' : ''}>
    {#if selectedId === null}
      <div
        class="hidden lg:flex items-center justify-center h-64 rounded-2xl border border-dashed
               border-gray-300 text-[13.5px] text-gray-400"
      >
        Choose a conversation to read it.
      </div>
    {:else}
      <a
        href="#conversations"
        class="lg:hidden inline-flex items-center min-h-9 mb-2 text-[14.5px] text-link"
      >
        ‹ Conversations
      </a>

      <article class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
        {#if detailError}
          <p class="px-5 py-6 text-[13.5px] text-danger" role="alert">{detailError}</p>
        {:else if !detail}
          <p class="px-5 py-6 text-[13.5px] text-gray-400">Loading…</p>
        {:else}
          <header class="px-5 py-4 border-b border-gray-200">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <h2 class="text-[17px] font-semibold">{whoName(detail)}</h2>
              {@render status(detail)}
            </div>
            <p class="mt-0.5 text-[13.5px] text-gray-500">
              {#if detail.phone}{formatPhone(detail.phone)} ·{/if}
              {formatDate(detail.started_at)} · {duration(detail)} · {PIPELINE_NAMES[detail.channel]}
            </p>
          </header>

          <ol
            class="flex flex-col gap-1.5 px-4 py-5 lg:max-h-[calc(100vh-280px)] lg:overflow-y-auto"
            aria-label="Transcript"
          >
            {#each detail.messages as m, i (m.id)}
              {#if m.role === 'tool'}
                <li class="self-center max-w-[90%] my-1">
                  <details class="text-[12.5px] text-gray-500">
                    <summary class="cursor-pointer list-inside text-center">⚙︎ {toolSummary(m)}</summary>
                    <p class="mt-1 px-3 py-2 rounded-lg bg-gray-100 text-gray-600">{m.text}</p>
                  </details>
                </li>
              {:else}
                {@const agent = m.role === 'agent'}
                <li class="flex flex-col {agent ? 'items-end' : 'items-start'}">
                  {#if showSender(detail.messages, i)}
                    <span class="mt-2 mb-0.5 px-3 text-[12.5px] text-gray-400">
                      {agent ? 'Agent' : whoName(detail)}
                    </span>
                  {/if}
                  <p
                    class="max-w-[80%] px-3.5 py-2 rounded-[18px] text-[14.5px] leading-snug
                           {agent ? 'bg-accent-soft text-gray-900' : 'bg-gray-100 text-gray-900'}"
                  >
                    {m.text}
                  </p>
                </li>
              {/if}
            {:else}
              <li class="text-center text-[13.5px] text-gray-400">Nothing said yet.</li>
            {/each}
          </ol>
        {/if}
      </article>
    {/if}
  </div>
</div>
