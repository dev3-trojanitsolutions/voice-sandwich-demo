<script lang="ts">
  import { onMount } from 'svelte';
  import {
    formatDate,
    formatPhone,
    getCustomers,
    PIPELINE_NAMES,
    type OrderRecord,
  } from '../api';

  // Orders come with the customers (GET /api/customers), so this section
  // needs no endpoint of its own. The agent saves an order as confirmed or
  // cancelled; there is no status to change here.
  type Order = OrderRecord & { name: string; phone: string };
  type Filter = 'all' | 'confirmed' | 'cancelled';

  const REFRESH_MS = 5000;
  const FILTERS: { id: Filter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'confirmed', label: 'Confirmed' },
    { id: 'cancelled', label: 'Cancelled' },
  ];

  // `selectedId` comes from the #orders/<id> route
  let { selectedId = null }: { selectedId?: number | null } = $props();

  let orders = $state<Order[]>([]);
  let loaded = $state(false);
  let error = $state('');
  let query = $state('');
  let filter = $state<Filter>('all');

  let filtered = $derived.by(() => {
    const q = query.trim().toLowerCase();
    const digits = q.replace(/\D/g, '');
    return orders.filter((o) => {
      if (filter !== 'all' && o.status !== filter) return false;
      if (!q) return true;
      return (
        o.name.toLowerCase().includes(q) ||
        (digits && (o.phone.includes(digits) || String(o.id) === digits)) ||
        o.items.some((i) => i.item.toLowerCase().includes(q)) ||
        o.address.toLowerCase().includes(q)
      );
    });
  });

  let stats = $derived.by(() => {
    const confirmed = orders.filter((o) => o.status === 'confirmed');
    const revenue = confirmed.reduce((sum, o) => sum + (o.total || 0), 0);
    const priced = confirmed.filter((o) => o.total).length;
    return [
      { label: 'Orders', value: String(orders.length) },
      { label: 'Confirmed', value: String(confirmed.length) },
      { label: 'Cancelled', value: String(orders.length - confirmed.length) },
      { label: 'Revenue', value: rupees(revenue) },
      { label: 'Average Order', value: priced ? rupees(revenue / priced) : '—' },
    ];
  });

  let selected = $derived(orders.find((o) => o.id === selectedId) ?? null);

  function rupees(n: number): string {
    return `₹${Math.round(n).toLocaleString('en-IN')}`;
  }

  function itemsLine(order: Order): string {
    return order.items.map((i) => `${i.quantity} × ${i.item}`).join(', ');
  }

  function itemCount(order: Order): number {
    return order.items.reduce((n, i) => n + i.quantity, 0);
  }

  async function load() {
    try {
      const customers = await getCustomers();
      orders = customers
        .flatMap((c) => c.orders.map((o) => ({ ...o, name: c.name, phone: c.phone })))
        .sort((a, b) => b.created_at - a.created_at);
      error = '';
    } catch (e) {
      error = `Can't load orders. ${(e as Error).message}`;
    } finally {
      loaded = true;
    }
  }

  function open(order: Order) {
    location.hash = `orders/${order.id}`;
  }

  function close() {
    location.hash = 'orders';
  }

  // The orders in view, as a CSV file with one row per order
  function exportCsv() {
    const cell = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
    const rows = [
      ['Order', 'Placed', 'Status', 'Customer', 'Phone', 'Items', 'Total', 'Payment', 'Address', 'Voice Model'],
      ...filtered.map((o) => [
        o.id,
        new Date(o.created_at * 1000).toISOString(),
        o.status,
        o.name,
        o.phone,
        itemsLine(o),
        o.total || '',
        o.payment_method,
        o.address,
        o.channel ? PIPELINE_NAMES[o.channel] : '',
      ]),
    ];
    const csv = rows.map((r) => r.map(cell).join(',')).join('\n');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    link.download = `orders-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  onMount(() => {
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load();
    }, REFRESH_MS);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectedId !== null) close();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      clearInterval(timer);
      window.removeEventListener('keydown', onKey);
    };
  });
</script>

{#snippet tag(status: Order['status'])}
  <span
    class="inline-flex items-center gap-1.5 h-[22px] px-2 rounded-full text-[12px] font-medium
           whitespace-nowrap {status === 'confirmed'
      ? 'bg-success/10 text-success'
      : 'bg-danger/10 text-danger'}"
  >
    <span class="w-1.5 h-1.5 rounded-full {status === 'confirmed' ? 'bg-success' : 'bg-danger'}"></span>
    {status === 'confirmed' ? 'Confirmed' : 'Cancelled'}
  </span>
{/snippet}

<div class="flex flex-col gap-[22px]">
  <div class="flex flex-wrap items-end justify-between gap-x-12 gap-y-3">
    <dl class="flex flex-wrap gap-x-12 gap-y-3">
      {#each stats as s (s.label)}
        <div class="flex flex-col gap-0.5">
          <dt class="text-[12.5px] text-gray-400">{s.label}</dt>
          <dd class="text-[22px] font-semibold tracking-[-0.025em] tabular-nums">
            {loaded ? s.value : '—'}
          </dd>
        </div>
      {/each}
    </dl>
    <button
      type="button"
      onclick={exportCsv}
      disabled={!filtered.length}
      class="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg border border-gray-300 bg-white
             text-[13.5px] font-medium hover:bg-gray-100 transition-colors cursor-pointer
             disabled:opacity-45 disabled:cursor-default"
    >
      <i class="ph ph-download-simple text-[15px]" aria-hidden="true"></i>
      Export CSV
    </button>
  </div>

  <div class="flex flex-wrap items-center gap-2.5">
    <div class="relative flex-[1_1_260px] max-w-[360px]">
      <i
        class="ph ph-magnifying-glass absolute left-[11px] top-1/2 -translate-y-1/2 text-[15px] text-gray-400"
        aria-hidden="true"
      ></i>
      <input
        type="search"
        bind:value={query}
        placeholder="Search order, customer, phone or item"
        aria-label="Search orders"
        class="search w-full h-9 pl-[33px] pr-3 rounded-lg border border-gray-300 bg-white text-[13.5px]"
      />
    </div>
    <div role="radiogroup" aria-label="Order status" class="inline-flex p-[3px] gap-0.5 rounded-[9px] bg-gray-100">
      {#each FILTERS as f (f.id)}
        <button
          type="button"
          role="radio"
          aria-checked={filter === f.id}
          onclick={() => (filter = f.id)}
          class="h-[30px] px-3 rounded-[7px] text-[13px] font-medium cursor-pointer transition-colors
                 {filter === f.id
            ? 'bg-white text-gray-900 shadow-[0_1px_2px_rgba(0,0,0,0.08)]'
            : 'text-gray-500 hover:text-gray-900'}"
        >
          {f.label}
        </button>
      {/each}
    </div>
    <span class="ml-auto text-[12.5px] text-gray-400">
      {filtered.length === 1 ? '1 order' : `${filtered.length} orders`}
    </span>
  </div>

  {#if !loaded}
    <p class="py-10 text-center text-[13.5px] text-gray-400" role="status">Loading…</p>
  {:else if error && !orders.length}
    <p class="py-10 text-center text-[13.5px] text-danger" role="alert">{error}</p>
  {:else if !orders.length}
    <div
      class="flex flex-col items-center text-center gap-2.5 px-4 py-20 border border-dashed
             border-gray-300 rounded-2xl"
    >
      <span class="w-11 h-11 rounded-xl grid place-items-center bg-accent-soft">
        <i class="ph ph-receipt text-[22px] text-link" aria-hidden="true"></i>
      </span>
      <p class="text-[15px] font-semibold">No orders yet</p>
      <p class="max-w-[400px] text-[13.5px] text-gray-500">
        When the agent takes an order in a conversation, it shows here with the customer, the
        items and the total.
      </p>
      <a
        href="/"
        class="mt-1 h-9 px-3.5 flex items-center rounded-lg bg-accent text-on-accent text-[13.5px]
               font-medium hover:bg-accent-hover transition-colors"
      >
        Open the Order Page
      </a>
    </div>
  {:else if !filtered.length}
    <div class="flex flex-col items-center text-center gap-2 px-4 py-16">
      <i class="ph ph-magnifying-glass text-[24px] text-gray-400" aria-hidden="true"></i>
      <p class="font-semibold">No orders match</p>
      <button
        type="button"
        onclick={() => {
          query = '';
          filter = 'all';
        }}
        class="mt-1 h-[34px] px-3 rounded-lg border border-gray-300 bg-white text-[13px] font-medium
               hover:bg-gray-100 cursor-pointer"
      >
        Clear Filters
      </button>
    </div>
  {:else}
    {#if error}
      <p class="text-[12.5px] text-danger" role="alert">{error}</p>
    {/if}
    <div class="border border-gray-200 rounded-2xl overflow-hidden">
      <div class="overflow-x-auto">
        <div class="min-w-[960px]" role="table" aria-label="Orders">
          <div
            role="row"
            class="row h-10 px-[18px] bg-gray-50 border-b border-gray-200 text-[12px] font-medium text-gray-400"
          >
            <span role="columnheader">Order</span>
            <span role="columnheader">Customer</span>
            <span role="columnheader">Items</span>
            <span role="columnheader">Total</span>
            <span role="columnheader">Status</span>
            <span role="columnheader">Placed</span>
            <span role="columnheader">Payment</span>
            <span></span>
          </div>
          {#each filtered as o (o.id)}
            <div
              role="row"
              tabindex="0"
              onclick={() => open(o)}
              onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), open(o))}
              class="row min-h-[58px] px-[18px] py-2 border-b border-gray-100 last:border-b-0
                     text-[13.5px] cursor-pointer transition-colors hover:bg-gray-50
                     {selectedId === o.id ? 'bg-gray-50' : ''}"
            >
              <span role="cell" class="flex flex-col">
                <span class="font-mono text-[12.5px] font-medium">#{o.id}</span>
                <span class="text-[12px] text-gray-400">
                  {o.channel ? PIPELINE_NAMES[o.channel] : '—'}
                </span>
              </span>
              <span role="cell" class="flex flex-col min-w-0">
                <span class="font-medium truncate">{o.name}</span>
                <span class="font-mono text-[11.5px] text-gray-400">{formatPhone(o.phone)}</span>
              </span>
              <span role="cell" class="text-[13px] text-gray-500 truncate">{itemsLine(o)}</span>
              <span role="cell" class="font-medium tabular-nums">{o.total ? rupees(o.total) : '—'}</span>
              <span role="cell">{@render tag(o.status)}</span>
              <span role="cell" class="text-[13px] text-gray-500">{formatDate(o.created_at)}</span>
              <span role="cell" class="text-[13px] truncate">{o.payment_method || '—'}</span>
              <i class="ph ph-caret-right text-[13px] text-gray-300" aria-hidden="true"></i>
            </div>
          {/each}
        </div>
      </div>
    </div>
  {/if}
</div>

{#if selected}
  <button
    type="button"
    aria-label="Close order"
    onclick={close}
    class="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px] cursor-default"
  ></button>
  <div
    role="dialog"
    aria-modal="true"
    aria-labelledby="order-title"
    class="fixed top-0 right-0 z-50 h-full w-[min(440px,100vw)] flex flex-col bg-white
           border-l border-gray-200 shadow-[0_24px_64px_rgba(0,0,0,0.2)]"
  >
    <header class="flex items-start gap-3 px-5 py-4 border-b border-gray-200">
      <div class="flex-1 min-w-0">
        <p class="flex items-center gap-2">
          <span id="order-title" class="font-mono text-[15px] font-semibold">Order #{selected.id}</span>
          {@render tag(selected.status)}
        </p>
        <p class="mt-0.5 text-[12.5px] text-gray-400">
          {formatDate(selected.created_at)}{selected.channel
            ? ` · ${PIPELINE_NAMES[selected.channel]}`
            : ''}
        </p>
      </div>
      <!-- svelte-ignore a11y_autofocus -->
      <button
        type="button"
        aria-label="Close"
        onclick={close}
        autofocus
        class="w-8 h-8 grid place-items-center rounded-lg text-gray-500 hover:bg-gray-100 cursor-pointer"
      >
        <i class="ph ph-x text-[17px]" aria-hidden="true"></i>
      </button>
    </header>

    <div class="flex-1 overflow-y-auto px-5 py-5 flex flex-col gap-6">
      <section aria-labelledby="order-customer" class="flex items-center gap-3">
        <span
          class="w-10 h-10 shrink-0 rounded-full bg-gray-100 grid place-items-center text-[13px] font-semibold"
          aria-hidden="true"
        >
          {selected.name.charAt(0).toUpperCase()}
        </span>
        <div class="flex-1 min-w-0">
          <p id="order-customer" class="font-medium truncate">{selected.name}</p>
          <p class="font-mono text-[12.5px] text-gray-500">{formatPhone(selected.phone)}</p>
        </div>
      </section>

      <section aria-labelledby="order-items">
        <h3 id="order-items" class="mb-2 text-[12px] font-medium text-gray-400">
          {itemCount(selected) === 1 ? '1 item' : `${itemCount(selected)} items`}
        </h3>
        <ul class="border border-gray-200 rounded-xl">
          {#each selected.items as item, i (i)}
            <li class="flex items-baseline gap-3 px-4 py-2.5 border-b border-gray-100 last:border-b-0">
              <span class="w-8 shrink-0 font-mono text-[12.5px] text-gray-500">{item.quantity}×</span>
              <span class="flex-1 min-w-0">{item.item}</span>
              {#if item.price !== undefined}
                <span class="tabular-nums text-gray-600">{rupees(item.quantity * item.price)}</span>
              {/if}
            </li>
          {/each}
          {#if selected.total}
            <li class="flex items-baseline gap-3 px-4 py-2.5 bg-gray-50 rounded-b-xl font-semibold">
              <span class="flex-1">Total</span>
              <span class="tabular-nums">{rupees(selected.total)}</span>
            </li>
          {/if}
        </ul>
      </section>

      <section aria-label="Order details">
        <dl class="grid grid-cols-[110px_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-[13.5px]">
          <dt class="text-gray-400">Payment</dt>
          <dd>{selected.payment_method || '—'}</dd>
          <dt class="text-gray-400">Address</dt>
          <dd class="break-words">{selected.address || '—'}</dd>
          {#each Object.entries(selected.details ?? {}) as [key, value] (key)}
            <dt class="text-gray-400 capitalize">{key.replace(/_/g, ' ')}</dt>
            <dd class="break-words">{value}</dd>
          {/each}
        </dl>
      </section>
    </div>

    <footer class="flex flex-wrap gap-2 px-5 py-4 border-t border-gray-200">
      <a
        href="#conversations?q={selected.phone}"
        class="h-9 px-3.5 flex items-center gap-1.5 rounded-lg bg-accent text-on-accent text-[13.5px]
               font-medium hover:bg-accent-hover transition-colors"
      >
        <i class="ph ph-chats-circle text-[15px]" aria-hidden="true"></i>
        View Conversations
      </a>
      <a
        href="#customers"
        class="h-9 px-3.5 flex items-center rounded-lg border border-gray-300 bg-white text-[13.5px]
               font-medium hover:bg-gray-100 transition-colors"
      >
        Customers
      </a>
    </footer>
  </div>
{/if}

<style>
  .row {
    display: grid;
    grid-template-columns:
      90px minmax(170px, 1.2fr) minmax(200px, 1.6fr) 90px 120px 120px minmax(90px, 0.6fr)
      16px;
    gap: 16px;
    align-items: center;
  }

  .search {
    color: var(--g900);
    outline: none;
  }

  .search::placeholder {
    color: var(--g400);
  }

  .search:focus {
    border-color: var(--brand);
    box-shadow: 0 0 0 3px rgb(255 91 31 / 0.14);
  }
</style>
