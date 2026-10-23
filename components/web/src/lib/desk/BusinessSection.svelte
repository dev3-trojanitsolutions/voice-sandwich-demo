<script lang="ts">
  import { onMount } from 'svelte';
  import {
    logoUrl,
    removeLogo,
    saveBrand,
    uploadLogo,
    type Brand,
    type BrandDetails,
  } from '../api';
  import { loadBrand, setBrand } from '../brand.svelte';
  import type { FullAutoFill } from 'svelte/elements';

  const LOGO_MAX_BYTES = 1024 * 1024;

  const fields: {
    key: keyof BrandDetails;
    label: string;
    placeholder: string;
    type?: string;
    autocomplete?: FullAutoFill;
    max: number;
  }[] = [
    { key: 'name', label: 'Name', placeholder: 'Ustad Hotel', autocomplete: 'organization', max: 60 },
    { key: 'description', label: 'About', placeholder: 'an Indian restaurant', max: 120 },
    { key: 'city', label: 'City', placeholder: 'Bangalore', autocomplete: 'address-level2', max: 60 },
    { key: 'phone', label: 'Phone', placeholder: '+91 98765 43210', type: 'tel', autocomplete: 'tel', max: 30 },
    { key: 'email', label: 'Email', placeholder: 'hello@example.com', type: 'email', autocomplete: 'email', max: 120 },
    { key: 'address', label: 'Address', placeholder: '12 MG Road, Bangalore 560001', autocomplete: 'street-address', max: 300 },
    { key: 'icon', label: 'Icon', placeholder: '🍛', max: 8 },
  ];

  let saved = $state<Brand | null>(null);
  let form = $state<BrandDetails | null>(null);
  let error = $state('');
  let notice = $state('');
  let saving = $state(false);

  let logoError = $state('');
  let logoBusy = $state(false);
  let fileInput = $state<HTMLInputElement>();

  let logo = $derived(saved ? logoUrl(saved) : null);
  let changed = $derived(
    !!form && !!saved && fields.some((f) => form![f.key] !== saved![f.key]),
  );

  function show(next: Brand) {
    saved = next;
    setBrand(next);
    const { logo_version, ...details } = next;
    form = details;
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (!form) return;
    error = '';
    notice = '';
    if (!form.name.trim()) {
      error = 'Enter the business name.';
      return;
    }
    saving = true;
    try {
      show(await saveBrand(form));
      notice = 'Saved. The agent uses the new details from the next session.';
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  async function chooseLogo(event: Event) {
    const file = (event.currentTarget as HTMLInputElement).files?.[0];
    if (fileInput) fileInput.value = '';
    if (!file) return;
    logoError = '';
    if (file.size > LOGO_MAX_BYTES) {
      logoError = 'Use a logo smaller than 1 MB.';
      return;
    }
    logoBusy = true;
    try {
      const next = await uploadLogo(file);
      // Keep unsaved text edits
      const draft = form;
      show(next);
      if (draft) form = draft;
    } catch (e) {
      logoError = (e as Error).message;
    } finally {
      logoBusy = false;
    }
  }

  async function deleteLogo() {
    logoError = '';
    logoBusy = true;
    try {
      const draft = form;
      show(await removeLogo());
      if (draft) form = draft;
    } catch (e) {
      logoError = (e as Error).message;
    } finally {
      logoBusy = false;
    }
  }

  onMount(() => {
    loadBrand().then(show);
  });
</script>

<section aria-labelledby="business-title" class="max-w-2xl mb-8">
  <h2 id="business-title" class="group-title">Business</h2>

  {#if !form || !saved}
    <div class="bg-white rounded-2xl p-5 border border-gray-200">
      <p class="text-[13.5px] text-gray-400">Loading…</p>
    </div>
  {:else}
    <!-- Logo -->
    <div class="flex flex-wrap items-center gap-4 mb-4 px-5 py-4 bg-white rounded-2xl border border-gray-200">
      <div
        class="w-20 h-20 shrink-0 rounded-xl bg-gray-100 flex items-center justify-center overflow-hidden"
      >
        {#if logo}
          <img src={logo} alt="Current logo" class="max-w-full max-h-full object-contain" />
        {:else}
          <span class="text-[40px] leading-none" aria-hidden="true">
            {saved.icon || saved.name.charAt(0).toUpperCase()}
          </span>
        {/if}
      </div>
      <div class="flex-1 min-w-48">
        <p class="text-[14.5px] font-medium">Logo</p>
        <p class="text-[12.5px]" aria-live="polite">
          {#if logoError}
            <span class="text-danger">{logoError}</span>
          {:else}
            <span class="text-gray-400">
              PNG, JPEG, GIF or WebP, up to 1 MB. A square or wide image works best. Without a
              logo, the icon shows.
            </span>
          {/if}
        </p>
      </div>
      <div class="flex gap-2">
        {#if logo}
          <button
            type="button"
            onclick={deleteLogo}
            disabled={logoBusy}
            class="min-h-9 px-4 rounded-xl text-[13.5px] font-medium text-danger hover:bg-gray-100
                   transition-colors cursor-pointer disabled:opacity-60"
          >
            Remove
          </button>
        {/if}
        <button
          type="button"
          onclick={() => fileInput?.click()}
          disabled={logoBusy}
          class="min-h-9 px-4 rounded-xl bg-gray-100 text-[13.5px] font-semibold text-gray-900
                 hover:bg-gray-200 transition-colors cursor-pointer disabled:opacity-60"
        >
          {logoBusy ? 'Uploading…' : logo ? 'Change Logo' : 'Upload Logo'}
        </button>
        <input
          bind:this={fileInput}
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp"
          onchange={chooseLogo}
          class="hidden"
          aria-label="Logo file"
        />
      </div>
    </div>

    <!-- Details -->
    <form
      onsubmit={submit}
      novalidate
      class="bg-white rounded-2xl border border-gray-200 overflow-hidden"
    >
      {#each fields as field, i (field.key)}
        <label class="field {i ? 'border-t border-gray-200' : ''}">
          <span class="field-label">{field.label}</span>
          <input
            bind:value={form[field.key]}
            type={field.type ?? 'text'}
            autocomplete={field.autocomplete ?? 'off'}
            placeholder={field.placeholder}
            maxlength={field.max}
            class="field-input"
          />
        </label>
      {/each}
      <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
        <p class="flex-1 min-w-48 text-[12.5px]" aria-live="polite">
          {#if error}
            <span class="text-danger">{error}</span>
          {:else if notice && !changed}
            <span class="text-success">{notice}</span>
          {:else}
            <span class="text-gray-400">
              The agent says the name in its greeting, and gives the contact details when asked.
            </span>
          {/if}
        </p>
        <button
          type="submit"
          disabled={saving || !changed}
          class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                 hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-60
                 disabled:cursor-default"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  {/if}
</section>

<style>
  .field {
    display: flex;
    align-items: center;
    min-height: 46px;
    padding: 0 20px;
    cursor: text;
  }

  .field-label {
    width: 96px;
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
