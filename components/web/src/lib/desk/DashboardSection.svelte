<script lang="ts">
  import { onMount } from 'svelte';
  import {
    formatPhone,
    getConversations,
    getCustomers,
    PIPELINE_NAMES,
    type ConversationSummary,
    type OrderRecord,
    type User,
  } from '../api';

  // Built from the existing lists: GET /api/conversations (the latest 200)
  // and the orders that come with GET /api/customers. Each part shows only
  // when the user's role can view that data.
  type Order = OrderRecord & { name: string; phone: string };
  type Range = 'today' | '7d' | '30d';

  const REFRESH_MS = 10000;
  const DAY = 86400;
  const RANGES: { id: Range; label: string }[] = [
    { id: 'today', label: 'Today' },
    { id: '7d', label: '7 days' },
    { id: '30d', label: '30 days' },
  ];

  let { me }: { me: User } = $props();

  let seesConversations = $derived(me.permissions.includes('conversations.view'));
  let seesOrders = $derived(me.permissions.includes('customers.view'));

  let conversations = $state<ConversationSummary[]>([]);
  let orders = $state<Order[]>([]);
  let loaded = $state(false);
  let error = $state('');
  let range = $state<Range>('7d');
  let now = $state(Date.now() / 1000);

  function startOfDay(seconds: number): number {
    const d = new Date(seconds * 1000);
    d.setHours(0, 0, 0, 0);
    return d.getTime() / 1000;
  }

  // The period, and the same length of time just before it, for the change
  let period = $derived.by(() => {
    const today = startOfDay(now);
    const days = range === 'today' ? 1 : range === '7d' ? 7 : 30;
    const from = today - (days - 1) * DAY;
    return { from, days, prevFrom: from - days * DAY };
  });

  let inPeriod = $derived({
    conversations: conversations.filter((c) => c.started_at >= period.from),
    orders: orders.filter((o) => o.created_at >= period.from),
  });

  let before = $derived({
    conversations: conversations.filter(
      (c) => c.started_at >= period.prevFrom && c.started_at < period.from,
    ),
    orders: orders.filter((o) => o.created_at >= period.prevFrom && o.created_at < period.from),
  });

  function confirmed(list: Order[]): Order[] {
    return list.filter((o) => o.status === 'confirmed');
  }

  function revenue(list: Order[]): number {
    return confirmed(list).reduce((sum, o) => sum + (o.total || 0), 0);
  }

  function conversion(list: ConversationSummary[]): number | null {
    return list.length ? list.filter((c) => c.outcome === 'confirmed').length / list.length : null;
  }

  function avgLength(list: ConversationSummary[]): number | null {
    const ended = list.filter((c) => c.ended_at);
    if (!ended.length) return null;
    return ended.reduce((sum, c) => sum + (c.ended_at! - c.started_at), 0) / ended.length;
  }

  function rupees(n: number): string {
    return `₹${Math.round(n).toLocaleString('en-IN')}`;
  }

  function duration(seconds: number | null): string {
    if (seconds === null) return '—';
    const s = Math.round(seconds);
    return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
  }

  function percent(n: number | null): string {
    return n === null ? '—' : `${Math.round(n * 100)}%`;
  }

  // "+3 vs the 7 days before"; nothing to compare with shows a plain note
  function change(current: number, previous: number, format = (n: number) => String(n)): string {
    const label = range === 'today' ? 'vs yesterday' : `vs the ${period.days} days before`;
    const diff = current - previous;
    if (!diff) return `Same as ${label.slice(3)}`;
    return `${diff > 0 ? '+' : '−'}${format(Math.abs(diff))} ${label}`;
  }

  let kpis = $derived.by(() => {
    const c = inPeriod.conversations;
    const o = inPeriod.orders;
    const list: { label: string; value: string; note: string }[] = [];
    if (seesConversations) {
      list.push({
        label: 'Conversations',
        value: String(c.length),
        note: change(c.length, before.conversations.length),
      });
    }
    if (seesOrders) {
      const n = confirmed(o).length;
      list.push({
        label: 'Orders',
        value: String(n),
        note: change(n, confirmed(before.orders).length),
      });
      list.push({
        label: 'Revenue',
        value: rupees(revenue(o)),
        note: change(revenue(o), revenue(before.orders), rupees),
      });
    }
    if (seesConversations) {
      list.push({
        label: 'Conversion',
        value: percent(conversion(c)),
        note: 'Conversations that ended in an order',
      });
      list.push({
        label: 'Avg. Length',
        value: duration(avgLength(c)),
        note: 'From the greeting to the end',
      });
    }
    return list;
  });

  // One bar per hour today, or per day. The light top part is what didn't
  // end in an order.
  let bars = $derived.by(() => {
    const source = inPeriod.conversations;
    const slots =
      range === 'today'
        ? Array.from({ length: 24 }, (_, h) => ({
            from: period.from + h * 3600,
            to: period.from + (h + 1) * 3600,
            label: h % 3 === 0 ? `${h}:00` : '',
            tip: `${h}:00`,
          }))
        : Array.from({ length: period.days }, (_, i) => {
            const from = period.from + i * DAY;
            const d = new Date(from * 1000);
            const label = d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
            const short =
              period.days === 7
                ? d.toLocaleDateString(undefined, { weekday: 'short' })
                : i % 5 === 0
                  ? label
                  : '';
            return { from, to: from + DAY, label: short, tip: label };
          });
    const counted = slots.map((s) => {
      const list = source.filter((c) => c.started_at >= s.from && c.started_at < s.to);
      const ordered = list.filter((c) => c.outcome === 'confirmed').length;
      return { ...s, total: list.length, ordered };
    });
    const max = Math.max(1, ...counted.map((b) => b.total));
    return counted.map((b) => ({
      ...b,
      height: `${(b.total / max) * 100}%`,
      other: b.total ? `${((b.total - b.ordered) / b.total) * 100}%` : '0%',
    }));
  });

  // The latest conversations and orders, newest first
  let activity = $derived.by(() => {
    const items: { key: string; icon: string; tone: string; text: string; meta: string; at: number; href: string }[] = [];
    if (seesConversations) {
      for (const c of conversations.slice(0, 8)) {
        const who = c.name || (c.phone ? formatPhone(c.phone) : 'A customer');
        items.push({
          key: `c${c.id}`,
          icon: c.outcome === 'cancelled' ? 'ph-x-circle' : 'ph-chats-circle',
          tone: c.outcome === 'cancelled' ? 'text-danger' : 'text-gray-500',
          text: `${who} talked to the agent`,
          meta: `${PIPELINE_NAMES[c.channel] ?? c.channel} · ${c.message_count} messages${
            c.outcome === 'cancelled' ? ' · cancelled' : ''
          }`,
          at: c.started_at,
          href: `#conversations/${c.id}`,
        });
      }
    }
    if (seesOrders) {
      for (const o of orders.slice(0, 8)) {
        items.push({
          key: `o${o.id}`,
          icon: 'ph-receipt',
          tone: o.status === 'confirmed' ? 'text-link' : 'text-danger',
          text: `${o.name} ${o.status === 'confirmed' ? 'placed' : 'cancelled'} order #${o.id}`,
          meta: [o.total ? rupees(o.total) : '', o.items.map((i) => i.item).join(', ')]
            .filter(Boolean)
            .join(' · '),
          at: o.created_at,
          href: `#orders/${o.id}`,
        });
      }
    }
    return items.sort((a, b) => b.at - a.at).slice(0, 7);
  });

  // Each voice model in the period
  let models = $derived.by(() => {
    const ids = [...new Set(inPeriod.conversations.map((c) => c.channel))];
    return ids
      .map((id) => {
        const list = inPeriod.conversations.filter((c) => c.channel === id);
        const rate = conversion(list);
        return {
          id,
          name: PIPELINE_NAMES[id] ?? id,
          count: list.length,
          orders: list.filter((c) => c.outcome === 'confirmed').length,
          rate,
          avg: avgLength(list),
        };
      })
      .sort((a, b) => b.count - a.count);
  });

  // The most ordered items in confirmed orders
  let topItems = $derived.by(() => {
    const byName = new Map<string, { item: string; quantity: number; revenue: number }>();
    for (const o of confirmed(inPeriod.orders)) {
      for (const i of o.items) {
        const key = i.item.toLowerCase();
        const row = byName.get(key) ?? { item: i.item, quantity: 0, revenue: 0 };
        row.quantity += i.quantity;
        row.revenue += i.quantity * (i.price ?? 0);
        byName.set(key, row);
      }
    }
    const rows = [...byName.values()].sort((a, b) => b.quantity - a.quantity).slice(0, 6);
    const max = Math.max(1, ...rows.map((r) => r.quantity));
    return rows.map((r) => ({ ...r, width: `${(r.quantity / max) * 100}%` }));
  });

  function time(seconds: number): string {
    const d = new Date(seconds * 1000);
    const sameDay = startOfDay(seconds) === startOfDay(Date.now() / 1000);
    return sameDay
      ? d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })
      : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  }

  async function load() {
    try {
      const [convs, customers] = await Promise.all([
        seesConversations ? getConversations() : Promise.resolve([]),
        seesOrders ? getCustomers() : Promise.resolve([]),
      ]);
      conversations = convs;
      orders = customers
        .flatMap((c) => c.orders.map((o) => ({ ...o, name: c.name, phone: c.phone })))
        .sort((a, b) => b.created_at - a.created_at);
      now = Date.now() / 1000;
      error = '';
    } catch (e) {
      error = `Can't load the dashboard. ${(e as Error).message}`;
    } finally {
      loaded = true;
    }
  }

  onMount(() => {
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, REFRESH_MS);
    return () => clearInterval(timer);
  });
</script>

<div class="flex flex-col gap-7">
  <div class="flex flex-wrap items-center gap-2">
    <div role="radiogroup" aria-label="Period" class="inline-flex p-[3px] gap-0.5 rounded-[9px] bg-gray-100">
      {#each RANGES as r (r.id)}
        <button
          type="button"
          role="radio"
          aria-checked={range === r.id}
          onclick={() => (range = r.id)}
          class="h-[30px] px-3 rounded-[7px] text-[13px] font-medium cursor-pointer transition-colors
                 {range === r.id
            ? 'bg-white text-gray-900 shadow-[0_1px_2px_rgba(0,0,0,0.08)]'
            : 'text-gray-500 hover:text-gray-900'}"
        >
          {r.label}
        </button>
      {/each}
    </div>
    <button
      type="button"
      aria-label="Refresh"
      onclick={load}
      class="w-9 h-9 grid place-items-center rounded-lg border border-gray-300 bg-white text-gray-600
             hover:bg-gray-100 cursor-pointer"
    >
      <i class="ph ph-arrow-clockwise text-[16px]" aria-hidden="true"></i>
    </button>
    {#if error}
      <p class="text-[12.5px] text-danger" role="alert">{error}</p>
    {/if}
  </div>

  {#if !loaded}
    <div aria-busy="true" aria-label="Loading" class="flex flex-col gap-5">
      <div class="h-24 rounded-2xl bg-gray-100"></div>
      <div class="h-64 rounded-2xl bg-gray-100 opacity-70"></div>
    </div>
  {:else}
    <!-- Key numbers -->
    <div class="bg-white border border-gray-200 rounded-2xl overflow-hidden">
      <div class="kpis grid">
      {#each kpis as k (k.label)}
        <div class="flex flex-col gap-1.5 px-5 pt-[18px] pb-5 bg-white">
          <p class="text-[13px] text-gray-500">{k.label}</p>
          <p class="text-[28px] font-semibold tracking-[-0.03em] leading-[1.1] tabular-nums">{k.value}</p>
          <p class="text-[12px] text-gray-400">{k.note}</p>
        </div>
      {/each}
      </div>
    </div>

    <div class="grid gap-5 grid-cols-[repeat(auto-fit,minmax(min(100%,420px),1fr))]">
      {#if seesConversations}
        <section aria-labelledby="volume-title" class="card flex flex-col gap-[18px]">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 id="volume-title" class="card-title">Conversations</h2>
              <p class="text-[12.5px] text-gray-400">
                {range === 'today' ? 'By hour' : 'By day'} · hover a bar for the count
              </p>
            </div>
            <div class="flex gap-3.5 text-[12px] text-gray-500">
              <span class="flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-[2px] bg-brand"></span>Ordered
              </span>
              <span class="flex items-center gap-1.5">
                <span class="w-2 h-2 rounded-[2px] bg-brand-soft"></span>No order
              </span>
            </div>
          </div>
          {#if !inPeriod.conversations.length}
            <div class="flex flex-col items-center text-center gap-1.5 py-14">
              <i class="ph ph-chat-slash text-[26px] text-gray-400" aria-hidden="true"></i>
              <p class="font-medium">No conversations in this period</p>
              <p class="text-[13px] text-gray-400">Start a session on the order page to talk to the agent.</p>
            </div>
          {:else}
            <div class="flex flex-col gap-2">
              <div role="img" aria-label="Conversations per {range === 'today' ? 'hour' : 'day'}" class="chart">
                {#each bars as b (b.from)}
                  <div
                    class="flex-1 min-w-0 h-full flex flex-col justify-end"
                    title="{b.tip}: {b.total} conversations, {b.ordered} ordered"
                  >
                    {#if b.total}
                      <div
                        class="bar flex flex-col rounded-[5px_5px_2px_2px] overflow-hidden bg-brand"
                        style:height={b.height}
                      >
                        <div class="bg-brand-soft" style:height={b.other}></div>
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
              <div class="flex gap-1 pt-2 border-t border-gray-200" aria-hidden="true">
                {#each bars as b (b.from)}
                  <span class="flex-1 min-w-0 text-center text-[11px] text-gray-400 whitespace-nowrap tabular-nums">
                    {b.label}
                  </span>
                {/each}
              </div>
            </div>
          {/if}
        </section>
      {/if}

      <section aria-labelledby="activity-title" class="card flex flex-col gap-1.5">
        <h2 id="activity-title" class="card-title mb-2">Recent Activity</h2>
        {#if !activity.length}
          <p class="text-[13.5px] text-gray-400">Nothing yet. Conversations and orders show up here.</p>
        {/if}
        {#each activity as a (a.key)}
          <a
            href={a.href}
            class="grid grid-cols-[28px_minmax(0,1fr)_auto] gap-3 items-start -mx-2 px-2 py-2 rounded-lg
                   hover:bg-gray-50 transition-colors"
          >
            <span class="w-7 h-7 rounded-lg grid place-items-center bg-gray-100">
              <i class="ph {a.icon} text-[15px] {a.tone}" aria-hidden="true"></i>
            </span>
            <span class="flex flex-col gap-px min-w-0">
              <span class="text-[13.5px] leading-[1.35] truncate">{a.text}</span>
              <span class="text-[12px] text-gray-400 truncate">{a.meta}</span>
            </span>
            <span class="font-mono text-[11.5px] text-gray-400 pt-[3px]">{time(a.at)}</span>
          </a>
        {/each}
      </section>
    </div>

    <div class="grid gap-5 grid-cols-[repeat(auto-fit,minmax(min(100%,420px),1fr))]">
      {#if seesConversations}
        <section aria-labelledby="models-title" class="flex flex-col gap-3">
          <div class="flex items-baseline justify-between">
            <h2 id="models-title" class="card-title">Voice Models</h2>
            <span class="text-[12.5px] text-gray-400">In this period</span>
          </div>
          <div class="border border-gray-200 rounded-2xl overflow-hidden">
            <div class="overflow-x-auto">
              <div class="min-w-[460px]" role="table" aria-label="Voice models">
                <div role="row" class="model-row h-10 px-[18px] bg-gray-50 border-b border-gray-200 text-[12px] font-medium text-gray-400">
                  <span role="columnheader">Model</span>
                  <span role="columnheader">Conversations</span>
                  <span role="columnheader">Conversion</span>
                  <span role="columnheader">Avg. Length</span>
                </div>
                {#each models as m (m.id)}
                  <div role="row" class="model-row min-h-[54px] px-[18px] py-2 border-b border-gray-100 last:border-b-0 text-[13.5px]">
                    <span role="cell" class="flex items-center gap-2.5 min-w-0">
                      <span class="w-[30px] h-[30px] shrink-0 rounded-full grid place-items-center bg-gray-100 text-[12.5px] font-semibold">
                        {m.name.charAt(0)}
                      </span>
                      <span class="font-medium truncate">{m.name}</span>
                    </span>
                    <span role="cell" class="tabular-nums">
                      {m.count}
                      <span class="text-[12px] text-gray-400">· {m.orders} ordered</span>
                    </span>
                    <span role="cell" class="flex items-center gap-2.5">
                      <span class="flex-1 h-1 rounded-sm bg-gray-100 overflow-hidden">
                        <span class="block h-full rounded-sm bg-gray-900" style:width={percent(m.rate)}></span>
                      </span>
                      <span class="w-10 text-[13px] tabular-nums">{percent(m.rate)}</span>
                    </span>
                    <span role="cell" class="tabular-nums text-gray-600">{duration(m.avg)}</span>
                  </div>
                {:else}
                  <p class="px-[18px] py-5 text-[13.5px] text-gray-400">No conversations in this period.</p>
                {/each}
              </div>
            </div>
          </div>
        </section>
      {/if}

      {#if seesOrders}
        <section aria-labelledby="items-title" class="flex flex-col gap-3">
          <div class="flex items-baseline justify-between">
            <h2 id="items-title" class="card-title">Top Items</h2>
            <a href="#orders" class="text-[12.5px] font-medium text-link hover:text-link-hover">All Orders</a>
          </div>
          <div class="card flex flex-col gap-3.5">
            {#each topItems as t (t.item)}
              <div class="flex flex-col gap-1.5">
                <div class="flex items-baseline gap-3 text-[13.5px]">
                  <span class="flex-1 min-w-0 truncate">{t.item}</span>
                  <span class="tabular-nums font-medium">{t.quantity}</span>
                  <span class="w-16 text-right tabular-nums text-[12.5px] text-gray-400">
                    {t.revenue ? rupees(t.revenue) : '—'}
                  </span>
                </div>
                <span class="h-1 rounded-sm bg-gray-100 overflow-hidden">
                  <span class="block h-full rounded-sm bg-brand" style:width={t.width}></span>
                </span>
              </div>
            {:else}
              <p class="text-[13.5px] text-gray-400">No confirmed orders in this period.</p>
            {/each}
          </div>
        </section>
      {/if}
    </div>
  {/if}
</div>

<style>
  /* Hairlines between the tiles: each tile draws its right and bottom edge,
     and the grid reaches 1px past the frame so the outer ones are hidden. A
     short last row stays white. */
  .kpis {
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    margin: 0 -1px -1px 0;
  }

  .kpis > div {
    border-right: 1px solid var(--g200);
    border-bottom: 1px solid var(--g200);
  }

  .card {
    min-width: 0;
    padding: 20px;
    border: 1px solid var(--g200);
    border-radius: 14px;
  }

  .card-title {
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  .chart {
    display: flex;
    align-items: flex-end;
    gap: 4px;
    height: 210px;
    padding-top: 8px;
    background-image: linear-gradient(var(--g100) 1px, transparent 1px);
    background-size: 100% 52px;
    background-position: 0 7px;
  }

  .bar {
    transition:
      height 0.35s cubic-bezier(0.2, 0.8, 0.2, 1),
      opacity 0.15s;
  }

  .bar:hover {
    opacity: 0.82;
  }

  .model-row {
    display: grid;
    grid-template-columns: minmax(120px, 1.2fr) 150px minmax(120px, 1fr) 90px;
    gap: 16px;
    align-items: center;
  }
</style>
