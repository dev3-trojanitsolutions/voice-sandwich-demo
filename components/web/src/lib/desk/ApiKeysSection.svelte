<script lang="ts">
  import { onMount } from 'svelte';
  import { getApiKeys, removeApiKey, saveApiKey, type ApiKeyStatus, type KeyProvider } from '../api';

  // Called after a key changes, so the voice model settings can reload
  let { onchange }: { onchange?: () => void } = $props();

  // What each service does here, and where staff get a key
  const about: Record<KeyProvider, { use: string; company: string; url: string; site: string }> = {
    gemini: {
      use: 'Gemini mode: listens, thinks and speaks.',
      company: 'Google',
      url: 'https://aistudio.google.com/apikey',
      site: 'Google AI Studio',
    },
    assemblyai: {
      use: 'Speech to text for Local and Claude modes, when this Mac has none.',
      company: 'AssemblyAI',
      url: 'https://www.assemblyai.com/dashboard/api-keys',
      site: 'the AssemblyAI dashboard',
    },
    cartesia: {
      use: 'Text to speech for Local and Claude modes, when no voice of your own is in use.',
      company: 'Cartesia',
      url: 'https://play.cartesia.ai/keys',
      site: 'the Cartesia console',
    },
    anthropic: {
      use: 'Claude mode: the model that takes the order.',
      company: 'Anthropic',
      url: 'https://console.anthropic.com/settings/keys',
      site: 'the Anthropic console',
    },
  };

  let keys = $state<ApiKeyStatus[] | null>(null);
  let loadError = $state('');
  let editing = $state<KeyProvider | null>(null);
  let key = $state('');
  let busy = $state<KeyProvider | null>(null);
  // One message at a time, shown under the row it is about
  let message = $state<{ id: KeyProvider; text: string; error: boolean } | null>(null);

  function replace(status: ApiKeyStatus) {
    keys = keys?.map((k) => (k.id === status.id ? status : k)) ?? null;
  }

  function startEdit(id: KeyProvider) {
    editing = id;
    key = '';
    message = null;
  }

  function cancelEdit() {
    editing = null;
    key = '';
    message = null;
  }

  async function submit(event: SubmitEvent, item: ApiKeyStatus) {
    event.preventDefault();
    if (!key.trim()) {
      message = { id: item.id, text: 'Paste the API key.', error: true };
      return;
    }
    busy = item.id;
    message = null;
    try {
      replace(await saveApiKey(item.id, key));
      key = '';
      editing = null;
      message = {
        id: item.id,
        text: `Key checked with ${about[item.id].company} and saved. It is used from the next session.`,
        error: false,
      };
      onchange?.();
    } catch (e) {
      message = { id: item.id, text: (e as Error).message, error: true };
    } finally {
      busy = null;
    }
  }

  async function remove(item: ApiKeyStatus) {
    if (!confirm(`Remove the ${item.name} API key? The key from .env is used again, if there is one.`)) return;
    busy = item.id;
    message = null;
    try {
      const status = await removeApiKey(item.id);
      replace(status);
      message = {
        id: item.id,
        text: status.set ? 'Removed. Now using the key from .env.' : 'Removed.',
        error: false,
      };
      onchange?.();
    } catch (e) {
      message = { id: item.id, text: (e as Error).message, error: true };
    } finally {
      busy = null;
    }
  }

  onMount(() => {
    getApiKeys()
      .then((k) => (keys = k))
      .catch((e) => (loadError = `Can't load the API keys. ${(e as Error).message}`));
  });
</script>

<section aria-labelledby="keys-title" class="max-w-2xl mb-8">
  <h2 id="keys-title" class="group-title">API Keys</h2>
  <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden divide-y divide-gray-200">
    {#if !keys}
      <p class="px-5 py-4 text-[13.5px] {loadError ? 'text-danger' : 'text-gray-400'}" role={loadError ? 'alert' : undefined}>
        {loadError || 'Loading…'}
      </p>
    {:else}
      {#each keys as item (item.id)}
        {@const info = about[item.id]}
        <div>
          <div class="flex flex-wrap items-center gap-3 px-5 py-4">
            <div class="flex-1 min-w-48">
              <p class="text-[14.5px] font-medium">{item.name}</p>
              <p class="text-[12.5px] text-gray-500">{info.use}</p>
              <p class="mt-1 text-[13.5px] text-gray-500">
                {#if !item.set}
                  <span class="text-gray-400">Not set</span>
                {:else}
                  <span class="font-mono tabular-nums">••••••••{item.hint}</span>
                  <span class="text-[12.5px] text-gray-400">
                    · {item.source === 'desk' ? 'Saved here' : 'From .env'}
                  </span>
                {/if}
              </p>
            </div>
            {#if editing !== item.id}
              {#if item.source === 'desk'}
                <button
                  type="button"
                  onclick={() => remove(item)}
                  disabled={busy !== null}
                  class="min-h-9 px-4 rounded-xl text-[13.5px] font-medium text-danger hover:bg-gray-100
                         transition-colors cursor-pointer disabled:opacity-60"
                >
                  Remove
                </button>
              {/if}
              <button
                type="button"
                onclick={() => startEdit(item.id)}
                aria-label="{item.set ? 'Change' : 'Add'} {item.name} key"
                class="min-h-9 px-4 rounded-xl bg-gray-100 text-[13.5px] font-semibold text-gray-900
                       hover:bg-gray-200 transition-colors cursor-pointer"
              >
                {item.set ? 'Change Key' : 'Add Key'}
              </button>
            {/if}
          </div>

          {#if editing === item.id}
            <form onsubmit={(e) => submit(e, item)} novalidate class="border-t border-gray-200">
              <label class="field">
                <span class="field-label">Key</span>
                <!-- svelte-ignore a11y_autofocus -->
                <input
                  bind:value={key}
                  type="password"
                  autocomplete="off"
                  spellcheck="false"
                  placeholder="Paste the {item.name} key"
                  autofocus
                  class="field-input font-mono"
                />
              </label>
              <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
                <p class="flex-1 min-w-48 text-[12.5px]" aria-live="polite">
                  {#if message?.id === item.id && message.error}
                    <span class="text-danger">{message.text}</span>
                  {:else}
                    <span class="text-gray-400">
                      Get a key from
                      <a href={info.url} target="_blank" rel="noreferrer" class="text-link font-medium"
                        >{info.site}</a
                      >. The key is checked with {info.company} before it is saved.
                    </span>
                  {/if}
                </p>
                <button
                  type="button"
                  onclick={cancelEdit}
                  class="min-h-9 px-4 rounded-xl text-[13.5px] font-medium text-gray-600 hover:bg-gray-100
                         transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={busy !== null}
                  class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                         hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-60"
                >
                  {busy === item.id ? 'Checking…' : 'Save Key'}
                </button>
              </div>
            </form>
          {:else if message?.id === item.id}
            <p
              class="px-5 py-3 border-t border-gray-200 text-[12.5px] {message.error ? 'text-danger' : 'text-success'}"
              aria-live="polite"
            >
              {message.text}
            </p>
          {/if}
        </div>
      {/each}
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
