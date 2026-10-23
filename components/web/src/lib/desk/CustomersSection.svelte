<script lang="ts">
  import { onMount } from 'svelte';
  import {
    addCustomer,
    formatDate,
    formatPhone,
    getCustomers,
    PIPELINE_NAMES,
    type Customer,
  } from '../api';

  const REFRESH_MS = 5000;

  let customers = $state<Customer[]>([]);
  let loaded = $state(false);
  let listError = $state('');
  let query = $state('');
  let expanded = $state<Record<string, boolean>>({});

  let name = $state('');
  let phone = $state('');
  let formError = $state('');
  let formNotice = $state('');
  let saving = $state(false);

  let filtered = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (!q) return customers;
    const digits = q.replace(/\D/g, '');
    return customers.filter(
      (c) => c.name.toLowerCase().includes(q) || (digits && c.phone.includes(digits)),
    );
  });

  async function loadCustomers() {
    try {
      customers = await getCustomers();
      listError = '';
    } catch (e) {
      listError = `Can't load customers. ${(e as Error).message}`;
    } finally {
      loaded = true;
    }
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    formError = '';
    formNotice = '';
    const digits = phone.replace(/\D/g, '').replace(/^91(?=\d{10}$)/, '');
    if (!name.trim()) {
      formError = "Enter the customer's name.";
      return;
    }
    if (digits.length !== 10) {
      formError = 'Enter a 10-digit phone number.';
      return;
    }
    saving = true;
    try {
      const saved = await addCustomer(name, digits);
      formNotice = `${saved.name} saved.`;
      name = '';
      phone = '';
      await loadCustomers();
    } catch (e) {
      formError = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  function itemCount(customer: Customer): number {
    return customer.orders.reduce(
      (sum, o) => sum + o.items.reduce((n, i) => n + i.quantity, 0),
      0,
    );
  }

  function itemsText(order: Customer['orders'][number]): string {
    return order.items
      .map((i) =>
        i.price === undefined
          ? `${i.quantity} × ${i.item}`
          : `${i.quantity} × ${i.item} · ₹${i.quantity * i.price}`,
      )
      .join(', ');
  }

  onMount(() => {
    loadCustomers();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') loadCustomers();
    }, REFRESH_MS);
    return () => clearInterval(timer);
  });
</script>

<!-- Add customer -->
<div class="max-w-2xl">
<section aria-labelledby="add-title" class="mb-8">
  <h2 id="add-title" class="group-title">Add Customer</h2>
  <form
    onsubmit={submit}
    novalidate
    class="bg-white rounded-2xl border border-gray-200 overflow-hidden"
  >
    <label class="field">
      <span class="field-label">Name</span>
      <input
        bind:value={name}
        name="name"
        autocomplete="name"
        placeholder="Asha Rao"
        class="field-input"
      />
    </label>
    <label class="field border-t border-gray-200">
      <span class="field-label">Phone</span>
      <span class="text-[14.5px] text-gray-400 mr-1.5" aria-hidden="true">+91</span>
      <input
        bind:value={phone}
        name="phone"
        type="tel"
        inputmode="numeric"
        autocomplete="tel-national"
        placeholder="98765 43210"
        aria-describedby="phone-hint"
        class="field-input"
      />
    </label>
    <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
      <p id="phone-hint" class="flex-1 min-w-48 text-[12.5px]" aria-live="polite">
        {#if formError}
          <span class="text-danger">{formError}</span>
        {:else if formNotice}
          <span class="text-success">{formNotice}</span>
        {:else}
          <span class="text-gray-400">10-digit mobile number. An existing number gets the new name.</span>
        {/if}
      </p>
      <button
        type="submit"
        disabled={saving}
        class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
               hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-60"
      >
        {saving ? 'Saving…' : 'Add Customer'}
      </button>
    </div>
  </form>
</section>

<!-- Customers -->
<section aria-labelledby="list-title">
  <div class="flex items-baseline justify-between">
    <h2 id="list-title" class="group-title">All Customers</h2>
    {#if customers.length}
      <span class="text-[12.5px] text-gray-400 mb-2">{customers.length} total</span>
    {/if}
  </div>

  {#if customers.length > 3}
    <input
      bind:value={query}
      type="search"
      placeholder="Search by name or phone"
      aria-label="Search customers"
      class="w-full min-h-9 mb-3 px-4 rounded-xl bg-gray-100 text-[14.5px] text-gray-900
             placeholder:text-gray-400 border-none"
    />
  {/if}

  <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
    {#if listError}
      <p class="px-5 py-6 text-[13.5px] text-danger" role="alert">{listError}</p>
    {:else if !loaded}
      <p class="px-5 py-6 text-[13.5px] text-gray-400">Loading…</p>
    {:else if customers.length === 0}
      <div class="px-5 py-10 text-center">
        <p class="text-[14.5px] font-semibold">No customers yet</p>
        <p class="mt-1 text-[13.5px] text-gray-500">
          A customer appears here when they give a phone number during an order, or when you
          add one above.
        </p>
      </div>
    {:else if filtered.length === 0}
      <p class="px-5 py-6 text-[13.5px] text-gray-500">No customer matches “{query}”.</p>
    {:else}
      <ul>
        {#each filtered as customer (customer.phone)}
          {@const open = expanded[customer.phone]}
          {@const items = itemCount(customer)}
          <li class="border-t border-gray-200 first:border-t-0">
            <button
              onclick={() => (expanded[customer.phone] = !open)}
              aria-expanded={!!open}
              aria-controls="orders-{customer.phone}"
              class="w-full flex items-center gap-4 px-5 py-3.5 min-h-16 text-left
                     hover:bg-gray-100 transition-colors cursor-pointer"
            >
              <span
                class="w-10 h-10 shrink-0 rounded-full bg-accent-soft text-link
                       flex items-center justify-center text-[14.5px] font-semibold"
                aria-hidden="true"
              >
                {customer.name.charAt(0).toUpperCase()}
              </span>
              <span class="flex-1 min-w-0">
                <span class="block text-[14.5px] font-medium truncate">{customer.name}</span>
                <span class="block text-[13.5px] text-gray-500 tabular-nums">
                  {formatPhone(customer.phone)}
                </span>
              </span>
              <span class="text-right shrink-0">
                <span class="block text-[13.5px] text-gray-600">
                  {customer.orders.length === 1 ? '1 order' : `${customer.orders.length} orders`}
                </span>
                <span class="block text-[12.5px] text-gray-400">
                  {items === 1 ? '1 item' : `${items} items`}
                </span>
              </span>
              <svg
                class="w-3 h-3 shrink-0 text-gray-400 transition-transform {open ? 'rotate-90' : ''}"
                viewBox="0 0 12 12"
                aria-hidden="true"
              >
                <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>

            {#if open}
              <div id="orders-{customer.phone}" class="px-5 pb-4 pl-[76px]">
                {#if customer.orders.length === 0}
                  <p class="text-[13.5px] text-gray-500">No orders yet.</p>
                {:else}
                  <ol class="flex flex-col gap-2.5">
                    {#each customer.orders as order (order.id)}
                      <li class="rounded-xl bg-gray-100 px-4 py-3">
                        <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]">
                          <span
                            class="font-semibold {order.status === 'confirmed'
                              ? 'text-success'
                              : 'text-danger'}"
                          >
                            {order.status === 'confirmed' ? '✓ Confirmed' : '✕ Cancelled'}
                          </span>
                          <span class="text-gray-400">·</span>
                          <span class="text-gray-500">{formatDate(order.created_at)}</span>
                          {#if order.channel}
                            <span class="text-gray-400">·</span>
                            <span class="text-gray-500">{PIPELINE_NAMES[order.channel]}</span>
                          {/if}
                          {#if order.total}
                            <span class="ml-auto font-semibold text-gray-900">
                              Total ₹{order.total}
                            </span>
                          {/if}
                        </div>
                        <p class="mt-1 text-[13.5px] text-gray-900">{itemsText(order)}</p>
                        <p class="mt-0.5 text-[12.5px] text-gray-500">
                          {order.payment_method} · {order.address}
                        </p>
                        {#if Object.keys(order.details ?? {}).length}
                          <p class="mt-0.5 text-[12.5px] text-gray-500">
                            {Object.entries(order.details)
                              .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${value}`)
                              .join(' · ')}
                          </p>
                        {/if}
                      </li>
                    {/each}
                  </ol>
                {/if}
                <a
                  href="#conversations?q={customer.phone}"
                  class="inline-flex items-center min-h-9 mt-1 text-[13.5px] font-medium text-link"
                >
                  View Conversations
                </a>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {/if}
  </div>
</section>
</div>

<style>
  .field {
    display: flex;
    align-items: center;
    min-height: 46px;
    padding: 0 20px;
    cursor: text;
  }

  .field-label {
    width: 72px;
    flex-shrink: 0;
    font-size: 14px;
  }

  .field-input {
    flex: 1;
    min-width: 0;
    min-height: 36px;
    font-size: 14px;
    background: transparent;
    color: var(--g900);
    border: none;
    outline: none;
  }

  .field-input::placeholder {
    color: var(--g400);
  }

  .field:focus-within {
    box-shadow: inset 3px 0 0 var(--focus);
  }
</style>
