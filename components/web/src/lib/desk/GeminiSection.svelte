<script lang="ts">
  import { onMount } from 'svelte';
  import { getGeminiKey, removeGeminiKey, saveGeminiKey, type GeminiKeyStatus } from '../api';

  // Called after the key changes, so the voice model settings can reload
  let { onchange }: { onchange?: () => void } = $props();

  let status = $state<GeminiKeyStatus | null>(null);
  let key = $state('');
  let editing = $state(false);
  let error = $state('');
  let notice = $state('');
  let busy = $state(false);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    notice = '';
    if (!key.trim()) {
      error = 'Paste the API key.';
      return;
    }
    busy = true;
    try {
      status = await saveGeminiKey(key);
      key = '';
      editing = false;
      notice = 'Key checked with Google and saved. Gemini uses it from the next session.';
      onchange?.();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function remove() {
    const fallback = 'The key from .env is used again, if there is one.';
    if (!confirm(`Remove the Gemini API key? ${fallback}`)) return;
    error = '';
    notice = '';
    busy = true;
    try {
      status = await removeGeminiKey();
      notice = status.set ? 'Removed. Now using the key from .env.' : 'Removed.';
      onchange?.();
    } catch (e) {
      error = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    getGeminiKey()
      .then((s) => (status = s))
      .catch((e) => (error = `Can't load the Gemini key. ${(e as Error).message}`));
  });
</script>

<section aria-labelledby="gemini-title" class="max-w-2xl mb-8">
  <h2 id="gemini-title" class="group-title">Gemini</h2>
  <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
    <div class="flex flex-wrap items-center gap-3 px-5 py-4">
      <div class="flex-1 min-w-48">
        <p class="text-[14.5px] font-medium">API Key</p>
        <p class="text-[13.5px] text-gray-500">
          {#if !status}
            Loading…
          {:else if !status.set}
            Not set. Gemini needs a key.
          {:else}
            <span class="font-mono tabular-nums">••••••••{status.hint}</span>
            <span class="text-[12.5px] text-gray-400">
              · {status.source === 'desk' ? 'Saved here' : 'From .env'}
            </span>
          {/if}
        </p>
      </div>
      {#if status && !editing}
        {#if status.source === 'desk'}
          <button
            type="button"
            onclick={remove}
            disabled={busy}
            class="min-h-9 px-4 rounded-xl text-[13.5px] font-medium text-danger hover:bg-gray-100
                   transition-colors cursor-pointer disabled:opacity-60"
          >
            Remove
          </button>
        {/if}
        <button
          type="button"
          onclick={() => {
            editing = true;
            error = notice = '';
          }}
          class="min-h-9 px-4 rounded-xl bg-gray-100 text-[13.5px] font-semibold text-gray-900
                 hover:bg-gray-200 transition-colors cursor-pointer"
        >
          {status.set ? 'Change Key' : 'Add Key'}
        </button>
      {/if}
    </div>

    {#if editing}
      <form onsubmit={submit} novalidate class="border-t border-gray-200">
        <label class="field">
          <span class="field-label">Key</span>
          <!-- svelte-ignore a11y_autofocus -->
          <input
            bind:value={key}
            type="password"
            autocomplete="off"
            spellcheck="false"
            placeholder="Paste the key"
            autofocus
            class="field-input font-mono"
          />
        </label>
        <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
          <p class="flex-1 min-w-48 text-[12.5px]" aria-live="polite">
            {#if error}
              <span class="text-danger">{error}</span>
            {:else}
              <span class="text-gray-400">
                Get a key from
                <a
                  href="https://aistudio.google.com/apikey"
                  target="_blank"
                  rel="noreferrer"
                  class="text-link font-medium">Google AI Studio</a
                >. The key is checked with Google before it is saved.
              </span>
            {/if}
          </p>
          <button
            type="button"
            onclick={() => {
              editing = false;
              key = '';
              error = '';
            }}
            class="min-h-9 px-4 rounded-xl text-[13.5px] font-medium text-gray-600 hover:bg-gray-100
                   transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                   hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-60"
          >
            {busy ? 'Checking…' : 'Save Key'}
          </button>
        </div>
      </form>
    {:else if error || notice}
      <p
        class="px-5 py-3 border-t border-gray-200 text-[12.5px] {error ? 'text-danger' : 'text-success'}"
        aria-live="polite"
      >
        {error || notice}
      </p>
    {/if}
  </div>
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
