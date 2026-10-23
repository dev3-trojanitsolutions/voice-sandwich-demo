<script lang="ts">
  import { onMount } from 'svelte';
  import {
    addCity,
    addPincode,
    addZone,
    deleteCity,
    deletePincode,
    deleteZone,
    getDelivery,
    resetDelivery,
    updateCity,
    updatePincode,
    updateZone,
    type DeliveryCity,
    type DeliveryPincode,
    type DeliveryZone,
  } from '../api';

  let cities = $state<DeliveryCity[]>([]);
  let loaded = $state(false);
  let loadError = $state('');
  let error = $state('');
  let notice = $state('');
  let busy = $state(false);

  let cityId = $state<number | null>(null);
  let city = $derived(cities.find((c) => c.id === cityId) ?? cities[0] ?? null);
  let openZones = $state<number[]>([]);
  let query = $state('');

  // Forms. Only one edit form is open at a time.
  let cityForm = $state<{ name: string; aliases: string } | null>(null);
  let newCity = $state<{ name: string; aliases: string } | null>(null);
  let zoneForm = $state<{ id: number; name: string } | null>(null);
  let newZoneName = $state('');
  let pinForm = $state<{ old: string; pincode: string; areas: string; active: boolean; zoneId: number } | null>(null);
  let newPin = $state<{ zoneId: number; pincode: string; areas: string } | null>(null);

  let counts = $derived.by(() => {
    if (!city) return { pincodes: 0, delivering: 0 };
    const pins = city.zones.flatMap((z) => z.pincodes.map((p) => ({ z, p })));
    return {
      pincodes: pins.length,
      delivering: pins.filter(({ z, p }) => delivers(city, z, p)).length,
    };
  });

  let results = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return null;
    const found: { city: DeliveryCity; zone: DeliveryZone; pin: DeliveryPincode }[] = [];
    for (const c of cities)
      for (const z of c.zones)
        for (const p of z.pincodes)
          if (p.pincode.startsWith(q) || p.areas.some((a) => a.toLowerCase().includes(q)))
            found.push({ city: c, zone: z, pin: p });
    return found;
  });

  function delivers(c: DeliveryCity, z: DeliveryZone, p: DeliveryPincode) {
    return c.active && z.active && p.active;
  }

  function list(text: string) {
    return text.split(',').map((t) => t.trim()).filter(Boolean);
  }

  async function run(action: () => Promise<DeliveryCity[]>, done = '') {
    busy = true;
    error = '';
    notice = '';
    try {
      cities = await action();
      notice = done;
      return true;
    } catch (e) {
      error = (e as Error).message;
      return false;
    } finally {
      busy = false;
    }
  }

  function toggleZone(id: number) {
    openZones = openZones.includes(id) ? openZones.filter((z) => z !== id) : [...openZones, id];
  }

  function closeForms() {
    cityForm = newCity = zoneForm = pinForm = newPin = null;
    error = '';
  }

  function editPin(c: DeliveryCity, z: DeliveryZone, p: DeliveryPincode) {
    closeForms();
    cityId = c.id;
    if (!openZones.includes(z.id)) openZones = [...openZones, z.id];
    pinForm = { old: p.pincode, pincode: p.pincode, areas: p.areas.join(', '), active: p.active, zoneId: z.id };
    query = '';
  }

  async function saveCity(event: SubmitEvent) {
    event.preventDefault();
    if (!city || !cityForm) return;
    if (await run(() => updateCity(city.id, cityForm!.name, list(cityForm!.aliases), city.active), 'City saved.'))
      cityForm = null;
  }

  async function createCity(event: SubmitEvent) {
    event.preventDefault();
    if (!newCity) return;
    if (await run(() => addCity(newCity!.name, list(newCity!.aliases)), 'City added.')) {
      cityId = cities[cities.length - 1].id;
      newCity = null;
    }
  }

  async function removeCity() {
    if (!city || !confirm(`Delete ${city.name} with all its zones and pincodes?`)) return;
    const id = city.id;
    if (await run(() => deleteCity(id), 'City deleted.')) cityId = null;
  }

  async function saveZone(event: SubmitEvent, zone: DeliveryZone) {
    event.preventDefault();
    if (zoneForm && (await run(() => updateZone(zone.id, zoneForm!.name, zone.active), 'Zone saved.')))
      zoneForm = null;
  }

  async function createZone(event: SubmitEvent) {
    event.preventDefault();
    if (!city) return;
    const id = city.id;
    if (await run(() => addZone(id, newZoneName), 'Zone added.')) newZoneName = '';
  }

  async function removeZone(zone: DeliveryZone) {
    const n = zone.pincodes.length;
    if (!confirm(`Delete the zone ${zone.name}${n ? ` and its ${n} pincodes` : ''}?`)) return;
    await run(() => deleteZone(zone.id), 'Zone deleted.');
  }

  async function savePin(event: SubmitEvent) {
    event.preventDefault();
    if (!pinForm) return;
    const f = pinForm;
    const pin = { pincode: f.pincode, areas: list(f.areas), active: f.active };
    if (await run(() => updatePincode(f.old, pin, f.zoneId), `${f.pincode} saved.`)) {
      if (!openZones.includes(f.zoneId)) openZones = [...openZones, f.zoneId];
      pinForm = null;
    }
  }

  async function createPin(event: SubmitEvent) {
    event.preventDefault();
    if (!newPin) return;
    const f = newPin;
    if (await run(() => addPincode(f.zoneId, f.pincode, list(f.areas)), `${f.pincode.trim()} added.`))
      newPin = null;
  }

  async function removePin(pincode: string) {
    if (!confirm(`Delete pincode ${pincode}?`)) return;
    if (await run(() => deletePincode(pincode), `${pincode} deleted.`)) pinForm = null;
  }

  async function reset() {
    if (!confirm('Replace every city, zone and pincode with the India Post data? Your changes are lost.'))
      return;
    closeForms();
    if (await run(resetDelivery, 'Areas reset to the India Post data.')) cityId = null;
  }

  onMount(async () => {
    try {
      cities = await getDelivery();
    } catch (e) {
      loadError = `Can't load the delivery areas. ${(e as Error).message}`;
    } finally {
      loaded = true;
    }
  });
</script>

{#snippet status(on: boolean, label = 'Off')}
  {#if !on}
    <span class="px-2 py-0.5 rounded-full bg-gray-100 text-[12.5px] font-medium text-gray-500">{label}</span>
  {/if}
{/snippet}

{#snippet pinRow(c: DeliveryCity, z: DeliveryZone, p: DeliveryPincode, showZone: boolean)}
  <div class="flex items-center gap-3 px-4 py-2.5">
    <div class="flex-1 min-w-0">
      <p class="flex flex-wrap items-center gap-2">
        <span class="font-mono text-[14.5px] font-semibold tabular-nums">{p.pincode}</span>
        {#if showZone}<span class="text-[12.5px] text-gray-500">{c.name} · {z.name}</span>{/if}
        {@render status(delivers(c, z, p), p.active ? 'Zone off' : 'Off')}
      </p>
      <p class="text-[13.5px] text-gray-600 truncate">{p.areas.join(', ') || 'No area names'}</p>
    </div>
    <button
      onclick={() => editPin(c, z, p)}
      class="min-h-9 px-3 -mr-2 rounded-lg text-[13.5px] font-medium text-link hover:bg-gray-100 transition-colors cursor-pointer"
    >
      Edit
    </button>
  </div>
{/snippet}

<div class="max-w-3xl">
  <p class="mb-6 text-[13.5px] text-gray-600">
    Where the agent takes delivery orders. The agent asks for the door number, street and pincode,
    and checks the pincode here. A pincode gets delivery only when it, its zone and its city are all
    on. A change applies to the next address the agent checks.
  </p>

  {#if loadError}
    <p class="text-[13.5px] text-danger" role="alert">{loadError}</p>
  {:else if !loaded}
    <p class="text-[13.5px] text-gray-400">Loading…</p>
  {:else}
    <p class="min-h-5 mb-3 text-[12.5px]" aria-live="polite">
      {#if error}<span class="text-danger">{error}</span>{:else if notice}<span class="text-success">{notice}</span>{/if}
    </p>

    <!-- Find -->
    <section aria-labelledby="find-title" class="mb-8">
      <h2 id="find-title" class="group-title">Find a Pincode or Area</h2>
      <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
        <input
          bind:value={query}
          type="search"
          inputmode="search"
          aria-label="Pincode or area"
          placeholder="560034 or Koramangala"
          class="w-full min-h-11 px-5 text-[14.5px] bg-transparent border-none outline-none placeholder:text-gray-400"
        />
        {#if results}
          <div class="border-t border-gray-200" aria-live="polite">
            {#if results.length === 0}
              <p class="px-5 py-3 text-[13.5px] text-gray-500">
                Not in any zone, so the agent says we don't deliver there.
              </p>
            {:else}
              <ul class="max-h-96 overflow-y-auto">
                {#each results.slice(0, 50) as r (r.pin.pincode)}
                  <li class="border-t border-gray-200 first:border-t-0">{@render pinRow(r.city, r.zone, r.pin, true)}</li>
                {/each}
              </ul>
            {/if}
          </div>
        {/if}
      </div>
    </section>

    <!-- Cities -->
    <section aria-labelledby="cities-title" class="mb-8">
      <div class="flex items-baseline justify-between">
        <h2 id="cities-title" class="group-title">Cities</h2>
        <button onclick={reset} disabled={busy} class="mb-2 text-[12.5px] font-medium text-link cursor-pointer">
          Reset to India Post Data
        </button>
      </div>
      <div class="flex flex-wrap gap-2" role="tablist" aria-label="Cities">
        {#each cities as c (c.id)}
          <button
            role="tab"
            aria-selected={c.id === city?.id}
            onclick={() => { closeForms(); cityId = c.id; }}
            class="min-h-9 px-4 rounded-full text-[13.5px] font-medium transition-colors cursor-pointer
                   {c.id === city?.id ? 'bg-accent text-on-accent' : 'bg-white border border-gray-200 text-gray-700 hover:bg-gray-100'}"
          >
            {c.name}{c.active ? '' : ' · Off'}
          </button>
        {/each}
        <button
          onclick={() => { closeForms(); newCity = { name: '', aliases: '' }; }}
          class="min-h-9 px-4 rounded-full text-[13.5px] font-medium text-link hover:bg-gray-100 transition-colors cursor-pointer"
        >
          + Add City
        </button>
      </div>

      {#if newCity}
        <form onsubmit={createCity} class="mt-3 bg-white rounded-2xl border border-gray-200 px-5 py-4 flex flex-col gap-3">
          <label class="block">
            <span class="block text-[12.5px] font-medium text-gray-500">City</span>
            <input bind:value={newCity.name} maxlength="60" placeholder="Mysuru" class="input" />
          </label>
          <label class="block">
            <span class="block text-[12.5px] font-medium text-gray-500">Other names customers use, separated by commas (optional)</span>
            <input bind:value={newCity.aliases} placeholder="Mysore" class="input" />
          </label>
          <div class="flex justify-end gap-2">
            <button type="button" onclick={() => (newCity = null)} class="btn-plain">Cancel</button>
            <button type="submit" disabled={busy} class="btn-primary">Add City</button>
          </div>
        </form>
      {/if}
    </section>

    {#if city}
      <!-- Selected city -->
      <section aria-labelledby="city-title" class="mb-8">
        <div class="bg-white rounded-2xl border border-gray-200 px-5 py-4">
          {#if cityForm}
            <form onsubmit={saveCity} class="flex flex-col gap-3">
              <label class="block">
                <span class="block text-[12.5px] font-medium text-gray-500">City</span>
                <input bind:value={cityForm.name} maxlength="60" class="input" />
              </label>
              <label class="block">
                <span class="block text-[12.5px] font-medium text-gray-500">Other names customers use, separated by commas</span>
                <input bind:value={cityForm.aliases} class="input" />
              </label>
              <div class="flex flex-wrap justify-between gap-2">
                <button type="button" onclick={removeCity} class="btn-plain text-danger! -ml-3">Delete City</button>
                <div class="flex gap-2">
                  <button type="button" onclick={() => (cityForm = null)} class="btn-plain">Cancel</button>
                  <button type="submit" disabled={busy} class="btn-primary">Save</button>
                </div>
              </div>
            </form>
          {:else}
            <div class="flex items-start gap-3">
              <div class="flex-1 min-w-0">
                <h2 id="city-title" class="text-[19px] font-bold tracking-tight">{city.name}</h2>
                <p class="text-[13.5px] text-gray-600">
                  {city.zones.length} zones · {counts.pincodes} pincodes · {counts.delivering} with delivery
                </p>
                {#if city.aliases.length}
                  <p class="mt-1 text-[12.5px] text-gray-500">Also called {city.aliases.join(', ')}</p>
                {/if}
              </div>
              <button
                onclick={() => { closeForms(); cityForm = { name: city.name, aliases: city.aliases.join(', ') }; }}
                class="min-h-9 px-3 rounded-lg text-[13.5px] font-medium text-link hover:bg-gray-100 transition-colors cursor-pointer"
              >
                Edit
              </button>
              <label class="flex items-center gap-2 min-h-9">
                <span class="sr-only">Deliver in {city.name}</span>
                <input
                  type="checkbox"
                  checked={city.active}
                  disabled={busy}
                  onchange={(e) => run(() => updateCity(city.id, city.name, city.aliases, e.currentTarget.checked))}
                  class="switch"
                />
              </label>
            </div>
          {/if}
        </div>
      </section>

      <!-- Zones -->
      <section aria-labelledby="zones-title" class="mb-8">
        <h2 id="zones-title" class="group-title">Zones in {city.name}</h2>
        <ul class="flex flex-col gap-3">
          {#each city.zones as zone (zone.id)}
            {@const open = openZones.includes(zone.id)}
            <li class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
              {#if zoneForm?.id === zone.id}
                <form onsubmit={(e) => saveZone(e, zone)} class="px-5 py-4 flex flex-col gap-3">
                  <label class="block">
                    <span class="block text-[12.5px] font-medium text-gray-500">Zone</span>
                    <input bind:value={zoneForm.name} maxlength="60" class="input" />
                  </label>
                  <div class="flex flex-wrap justify-between gap-2">
                    <button type="button" onclick={() => removeZone(zone)} class="btn-plain text-danger! -ml-3">Delete Zone</button>
                    <div class="flex gap-2">
                      <button type="button" onclick={() => (zoneForm = null)} class="btn-plain">Cancel</button>
                      <button type="submit" disabled={busy} class="btn-primary">Save</button>
                    </div>
                  </div>
                </form>
              {:else}
                <div class="flex items-center gap-2 pl-2 pr-4 py-1.5">
                  <button
                    onclick={() => toggleZone(zone.id)}
                    aria-expanded={open}
                    class="flex-1 min-w-0 flex items-center gap-2 min-h-9 px-2 rounded-lg text-left hover:bg-gray-50 transition-colors cursor-pointer"
                  >
                    <svg viewBox="0 0 12 12" class="w-3 h-3 shrink-0 text-gray-400 transition-transform {open ? 'rotate-90' : ''}" aria-hidden="true">
                      <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                    </svg>
                    <span class="text-[14.5px] font-medium">{zone.name}</span>
                    <span class="text-[13.5px] text-gray-500">{zone.pincodes.length} {zone.pincodes.length === 1 ? 'pincode' : 'pincodes'}</span>
                    {@render status(zone.active)}
                  </button>
                  <button
                    onclick={() => { closeForms(); zoneForm = { id: zone.id, name: zone.name }; }}
                    class="min-h-9 px-3 rounded-lg text-[13.5px] font-medium text-link hover:bg-gray-100 transition-colors cursor-pointer"
                  >
                    Edit
                  </button>
                  <label class="flex items-center min-h-9">
                    <span class="sr-only">Deliver in {zone.name}</span>
                    <input
                      type="checkbox"
                      checked={zone.active}
                      disabled={busy}
                      onchange={(e) => run(() => updateZone(zone.id, zone.name, e.currentTarget.checked))}
                      class="switch"
                    />
                  </label>
                </div>
              {/if}

              {#if open}
                <ul class="border-t border-gray-200">
                  {#each zone.pincodes as pin (pin.pincode)}
                    <li class="border-t border-gray-100 first:border-t-0">
                      {#if pinForm?.old === pin.pincode}
                        <form onsubmit={savePin} class="px-4 py-3 bg-gray-50 flex flex-col gap-3">
                          <div class="grid grid-cols-1 sm:grid-cols-[10rem_1fr] gap-3">
                            <label class="block">
                              <span class="block text-[12.5px] font-medium text-gray-500">Pincode</span>
                              <input bind:value={pinForm.pincode} inputmode="numeric" maxlength="6" class="input bg-white! font-mono" />
                            </label>
                            <label class="block">
                              <span class="block text-[12.5px] font-medium text-gray-500">Zone</span>
                              <select bind:value={pinForm.zoneId} class="input bg-white!">
                                {#each cities as c (c.id)}
                                  <optgroup label={c.name}>
                                    {#each c.zones as z (z.id)}<option value={z.id}>{z.name}</option>{/each}
                                  </optgroup>
                                {/each}
                              </select>
                            </label>
                          </div>
                          <label class="block">
                            <span class="block text-[12.5px] font-medium text-gray-500">Areas, separated by commas</span>
                            <textarea bind:value={pinForm.areas} rows="2" class="input bg-white! py-2 resize-y"></textarea>
                          </label>
                          <label class="flex items-center justify-between min-h-9">
                            <span class="text-[13.5px]">Deliver to this pincode</span>
                            <input type="checkbox" bind:checked={pinForm.active} class="switch" />
                          </label>
                          <div class="flex flex-wrap justify-between gap-2">
                            <button type="button" onclick={() => removePin(pin.pincode)} class="btn-plain text-danger! -ml-3">Delete</button>
                            <div class="flex gap-2">
                              <button type="button" onclick={() => (pinForm = null)} class="btn-plain">Cancel</button>
                              <button type="submit" disabled={busy} class="btn-primary">Save</button>
                            </div>
                          </div>
                        </form>
                      {:else}
                        {@render pinRow(city, zone, pin, false)}
                      {/if}
                    </li>
                  {/each}
                  <li class="border-t border-gray-100">
                    {#if newPin?.zoneId === zone.id}
                      <form onsubmit={createPin} class="px-4 py-3 bg-gray-50 flex flex-col gap-3">
                        <div class="grid grid-cols-1 sm:grid-cols-[10rem_1fr] gap-3">
                          <label class="block">
                            <span class="block text-[12.5px] font-medium text-gray-500">Pincode</span>
                            <input bind:value={newPin.pincode} inputmode="numeric" maxlength="6" placeholder="560034" class="input bg-white! font-mono" />
                          </label>
                          <label class="block">
                            <span class="block text-[12.5px] font-medium text-gray-500">Areas, separated by commas</span>
                            <input bind:value={newPin.areas} placeholder="Koramangala, Agara" class="input bg-white!" />
                          </label>
                        </div>
                        <div class="flex justify-end gap-2">
                          <button type="button" onclick={() => (newPin = null)} class="btn-plain">Cancel</button>
                          <button type="submit" disabled={busy} class="btn-primary">Add Pincode</button>
                        </div>
                      </form>
                    {:else}
                      <button
                        onclick={() => { closeForms(); newPin = { zoneId: zone.id, pincode: '', areas: '' }; }}
                        class="w-full min-h-9 px-4 text-left text-[13.5px] font-medium text-link hover:bg-gray-50 transition-colors cursor-pointer"
                      >
                        + Add Pincode
                      </button>
                    {/if}
                  </li>
                </ul>
              {/if}
            </li>
          {/each}
        </ul>

        <form onsubmit={createZone} class="mt-3 flex items-center gap-3 bg-white rounded-2xl border border-gray-200 px-5 py-2">
          <input
            bind:value={newZoneName}
            maxlength="60"
            aria-label="New zone name"
            placeholder="New zone, e.g. Electronic City"
            class="flex-1 min-w-0 min-h-9 text-[14.5px] bg-transparent border-none outline-none placeholder:text-gray-400"
          />
          <button type="submit" disabled={busy || !newZoneName.trim()} class="btn-plain bg-gray-100 disabled:opacity-50">
            Add Zone
          </button>
        </form>
      </section>
    {/if}

    <p class="text-[12.5px] text-gray-500">
      The areas start from India Post data (the All India Pincode Directory, through
      api.postalpincode.in), with the postal divisions as zones. <code>make fetch-pincodes</code>
      downloads it again.
    </p>
  {/if}
</div>

<style>
  .input {
    width: 100%;
    min-height: 36px;
    margin-top: 4px;
    padding: 0 12px;
    border-radius: 10px;
    font-size: 14px;
    background: var(--g100);
    color: var(--g900);
    border: none;
    outline: none;
  }

  .input:focus {
    box-shadow: 0 0 0 2px var(--focus);
  }

  .btn-plain {
    min-height: 36px;
    padding: 0 16px;
    border-radius: 8px;
    font-size: 13.5px;
    font-weight: 600;
    color: var(--link);
    cursor: pointer;
  }

  .btn-plain:hover {
    background: var(--g100);
  }

  .btn-primary {
    min-height: 36px;
    padding: 0 20px;
    border-radius: 8px;
    font-size: 13.5px;
    font-weight: 600;
    background: var(--accent);
    color: var(--on-accent);
    cursor: pointer;
  }

  .btn-primary:disabled {
    opacity: 0.6;
  }

  .switch {
    appearance: none;
    position: relative;
    width: 51px;
    height: 31px;
    flex-shrink: 0;
    border-radius: 999px;
    background: var(--g300);
    cursor: pointer;
    transition: background 0.2s;
  }

  .switch::after {
    content: '';
    position: absolute;
    top: 2px;
    left: 2px;
    width: 27px;
    height: 27px;
    border-radius: 999px;
    background: white;
    box-shadow: 0 1px 3px rgb(0 0 0 / 0.25);
    transition: transform 0.2s;
  }

  .switch:checked {
    background: var(--success);
  }

  .switch:checked::after {
    transform: translateX(20px);
  }
</style>
