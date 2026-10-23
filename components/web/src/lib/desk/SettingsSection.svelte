<script lang="ts">
  import { onMount } from 'svelte';
  import { getSettings, setPipeline, type Pipeline, type Settings } from '../api';
  import VoicesSection from './VoicesSection.svelte';
  import BusinessSection from './BusinessSection.svelte';
  import GeminiSection from './GeminiSection.svelte';

  let settings = $state<Settings | null>(null);
  let switching = $state<Pipeline | null>(null);
  let modeError = $state('');

  const modes: { id: Pipeline; title: string; detail: (s: Settings) => string }[] = [
    {
      id: 'realtime',
      title: 'Gemini',
      detail: () =>
        'Google Gemini Live in the cloud. The fastest replies, and customers can interrupt the agent.',
    },
    {
      id: 'ollama',
      title: 'Local',
      detail: (s) =>
        `${s.local_model} on this Mac through Ollama. No cloud model, but replies take 1–5 seconds.`,
    },
  ];

  async function chooseMode(id: Pipeline) {
    if (!settings || switching || settings.pipeline === id) return;
    switching = id;
    modeError = '';
    try {
      settings = await setPipeline(id);
    } catch (e) {
      modeError = (e as Error).message;
    } finally {
      switching = null;
    }
  }

  // Arrow keys move the selection, like a native segmented control
  function onModeKey(event: KeyboardEvent) {
    if (!settings || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const index = modes.findIndex((m) => m.id === settings!.pipeline);
    const step = event.key === 'ArrowRight' ? 1 : -1;
    const next = modes[(index + step + modes.length) % modes.length];
    chooseMode(next.id);
    document.getElementById(`mode-${next.id}`)?.focus();
  }

  onMount(() => {
    getSettings()
      .then((s) => (settings = s))
      .catch((e) => (modeError = `Can't load settings. ${(e as Error).message}`));
  });
</script>

<BusinessSection />

<GeminiSection
  onchange={() =>
    getSettings()
      .then((s) => (settings = s))
      .catch(() => {})}
/>

<section aria-labelledby="mode-title" class="max-w-2xl">
  <h2 id="mode-title" class="group-title">Voice Model</h2>
  <div class="bg-white rounded-2xl p-5 border border-gray-200">
    {#if settings}
      <div
        role="radiogroup"
        aria-labelledby="mode-title"
        tabindex="-1"
        onkeydown={onModeKey}
        class="grid grid-cols-2 p-1 bg-gray-100 rounded-xl"
      >
        {#each modes as mode (mode.id)}
          {@const selected = settings.pipeline === mode.id}
          <button
            id="mode-{mode.id}"
            role="radio"
            aria-checked={selected}
            tabindex={selected || (settings.pipeline === 'sandwich' && mode.id === 'realtime') ? 0 : -1}
            disabled={switching !== null}
            onclick={() => chooseMode(mode.id)}
            class="min-h-9 rounded-[9px] text-[13.5px] font-semibold transition-colors cursor-pointer
                   disabled:cursor-wait
                   {selected
                     ? 'bg-accent text-on-accent shadow-sm'
                     : 'text-gray-600 hover:text-gray-900'}"
          >
            {switching === mode.id ? 'Switching…' : mode.title}
          </button>
        {/each}
      </div>

      {#if settings.pipeline === 'sandwich'}
        <p class="mt-4 text-[13.5px] text-gray-600">
          Now using Claude, set by <code class="font-mono text-sm">PIPELINE=sandwich</code> in
          .env. Choose a mode to replace it.
        </p>
      {:else}
        {@const active = modes.find((m) => m.id === settings!.pipeline)}
        <p class="mt-4 text-[13.5px] text-gray-600">{active?.detail(settings)}</p>
      {/if}

      <p class="mt-1 text-[12.5px] text-gray-400">The change applies to the next session.</p>

      <div aria-live="polite">
        {#if switching === 'ollama'}
          <p class="mt-3 text-[12.5px] text-gray-600">Loading the local model. This can take a minute.</p>
        {/if}
        {#if modeError}
          <p class="mt-3 text-[12.5px] text-danger">{modeError}</p>
        {/if}
      </div>
    {:else if modeError}
      <p class="text-[13.5px] text-danger" role="alert">{modeError}</p>
    {:else}
      <p class="text-[13.5px] text-gray-400">Loading…</p>
    {/if}
  </div>
</section>

<div class="mt-8">
  <VoicesSection />
</div>
