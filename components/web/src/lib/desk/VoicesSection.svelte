<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    addAccent,
    addVoice,
    chooseVoice,
    deleteVoice,
    getVoices,
    previewVoice,
    voiceAudioUrl,
    type Voice,
    type VoiceLibrary,
    type VoiceVersion,
  } from '../api';
  import { startRecording, toWav, wavSeconds, type Recording } from './recorder';

  let library = $state<VoiceLibrary | null>(null);
  let loadError = $state('');

  // Recording
  let recording = $state<Recording | null>(null);
  let elapsed = $state(0);
  let timer: ReturnType<typeof setInterval> | undefined;
  let take = $state<Blob | null>(null);
  let takeUrl = $state('');
  let name = $state('');
  let saving = $state(false);
  let recordError = $state('');

  // Voices
  // The voice being set: a voice ID, or null for Cartesia
  let choosing = $state<number | null | undefined>(undefined);
  let listError = $state('');
  let accentChoice = $state<Record<number, string>>({});
  let making = $state<{ voiceId: number; accent: string } | null>(null);
  let previewing = $state<number | null>(null);
  let player: HTMLAudioElement | null = null;
  let playing = $state<string>('');

  let ready = $derived(library?.service.ready ?? false);
  let takeSeconds = $derived(take ? wavSeconds(take) : 0);

  async function load() {
    try {
      library = await getVoices();
      loadError = '';
    } catch (e) {
      loadError = `Can't load voices. ${(e as Error).message}`;
    }
  }

  function setTake(wav: Blob | null) {
    if (takeUrl) URL.revokeObjectURL(takeUrl);
    take = wav;
    takeUrl = wav ? URL.createObjectURL(wav) : '';
  }

  async function record() {
    recordError = '';
    setTake(null);
    try {
      recording = await startRecording();
    } catch {
      recordError = 'The browser has no access to the microphone. Allow it in the site settings.';
      return;
    }
    elapsed = 0;
    timer = setInterval(() => {
      elapsed += 1;
      if (library && elapsed >= library.max_seconds) stop();
    }, 1000);
  }

  async function stop() {
    clearInterval(timer);
    const current = recording;
    recording = null;
    if (!current) return;
    try {
      setTake(await current.stop());
    } catch {
      recordError = "Can't read the recording. Try again.";
    }
  }

  async function upload(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    recordError = '';
    try {
      setTake(await toWav(file));
    } catch {
      recordError = "Can't read this file. Use a WAV, MP3 or M4A recording.";
    }
  }

  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!take || saving) return;
    if (!name.trim()) {
      recordError = 'Give the voice a name.';
      return;
    }
    saving = true;
    recordError = '';
    try {
      const voice = await addVoice(name, take);
      library!.voices = [...library!.voices, voice];
      setTake(null);
      name = '';
    } catch (e) {
      recordError = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  async function choose(id: number | null) {
    if (choosing !== undefined || library?.active_id === id) return;
    choosing = id;
    listError = '';
    try {
      library = await chooseVoice(id);
    } catch (e) {
      listError = (e as Error).message;
    } finally {
      choosing = undefined;
    }
  }

  async function makeAccent(voice: Voice) {
    const accent = accentChoice[voice.id];
    if (!accent || making) return;
    making = { voiceId: voice.id, accent };
    listError = '';
    try {
      const version = await addAccent(voice.id, accent);
      voice.versions = [...voice.versions, version];
      accentChoice[voice.id] = '';
    } catch (e) {
      listError = (e as Error).message;
    } finally {
      making = null;
    }
  }

  async function remove(voice: Voice | VoiceVersion, isOriginal: boolean) {
    const what = isOriginal
      ? `Delete the voice “${voice.name}” and all its accents?`
      : `Delete the ${voice.accent_label} accent of “${voice.name}”?`;
    if (!confirm(what)) return;
    listError = '';
    try {
      await deleteVoice(voice.id);
      await load();
    } catch (e) {
      listError = (e as Error).message;
    }
  }

  function play(key: string, url: string) {
    player?.pause();
    if (playing === key) {
      playing = '';
      return;
    }
    player = new Audio(url);
    playing = key;
    player.onended = () => (playing = '');
    player.play().catch(() => (playing = ''));
  }

  async function preview(id: number) {
    const key = `call-${id}`;
    if (playing === key) {
      play(key, '');
      return;
    }
    if (previewing !== null) return;
    previewing = id;
    listError = '';
    try {
      const wav = await previewVoice(id);
      play(key, URL.createObjectURL(wav));
    } catch (e) {
      listError = (e as Error).message;
    } finally {
      previewing = null;
    }
  }

  function unusedAccents(voice: Voice): [string, string][] {
    const made = new Set(voice.versions.map((v) => v.accent));
    return Object.entries(library!.accents).filter(([key]) => !made.has(key));
  }

  function clock(seconds: number) {
    return `0:${String(Math.floor(seconds)).padStart(2, '0')}`;
  }

  onMount(load);
  onDestroy(() => {
    clearInterval(timer);
    recording?.cancel();
    player?.pause();
    if (takeUrl) URL.revokeObjectURL(takeUrl);
  });
</script>

{#snippet playButton(key: string, url: string, label: string)}
  <button
    type="button"
    onclick={() => play(key, url)}
    aria-label={playing === key ? `Stop ${label}` : `Play ${label}`}
    class="shrink-0 w-11 h-11 flex items-center justify-center rounded-full bg-gray-100 text-link
           hover:bg-gray-200 transition-colors cursor-pointer"
  >
    {#if playing === key}
      <svg viewBox="0 0 16 16" class="w-4 h-4" aria-hidden="true"><rect x="3" y="3" width="10" height="10" rx="1.5" fill="currentColor" /></svg>
    {:else}
      <svg viewBox="0 0 16 16" class="w-4 h-4" aria-hidden="true"><path d="M4.5 2.8v10.4a.6.6 0 0 0 .9.5l8.3-5.2a.6.6 0 0 0 0-1L5.4 2.3a.6.6 0 0 0-.9.5z" fill="currentColor" /></svg>
    {/if}
  </button>
{/snippet}

{#snippet previewButton(id: number, label: string)}
  <button
    type="button"
    onclick={() => preview(id)}
    disabled={!ready || (previewing !== null && previewing !== id)}
    aria-label="Hear {label} the way callers do"
    class="shrink-0 min-h-9 px-3 rounded-xl text-[13.5px] font-semibold text-link
           hover:bg-gray-100 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-default"
  >
    {previewing === id ? 'Speaking…' : playing === `call-${id}` ? 'Stop' : 'Preview'}
  </button>
{/snippet}

{#snippet useButton(id: number | null, label: string, needsService: boolean)}
  {@const selected = library?.active_id === id}
  <button
    type="button"
    role="radio"
    aria-checked={selected}
    aria-label="Use {label} on calls"
    onclick={() => choose(id)}
    disabled={(needsService && !ready) || choosing !== undefined}
    class="shrink-0 min-h-9 min-w-20 px-3 rounded-xl text-[13.5px] font-semibold transition-colors cursor-pointer
           disabled:cursor-default
           {selected ? 'bg-accent text-on-accent' : 'bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50'}"
  >
    {choosing === id ? 'Setting…' : selected ? 'In Use' : 'Use'}
  </button>
{/snippet}

{#snippet voiceRow(v: VoiceVersion, isOriginal: boolean)}
  {@const label = `${v.name}, ${isOriginal ? 'original' : v.accent_label} accent`}
  <li class="flex items-center gap-2 sm:gap-3 px-4 py-2.5 border-t border-gray-200">
    {@render playButton(`sample-${v.id}`, voiceAudioUrl(v.id), `${v.accent_label} sample`)}
    <div class="flex-1 min-w-0">
      <p class="text-[14.5px] font-medium truncate">
        {isOriginal ? 'Original accent' : `${v.accent_label} accent`}
      </p>
      <p class="text-[12.5px] text-gray-500 truncate">
        {isOriginal ? 'Your recording, exactly as you spoke' : 'Made from your recording'}
      </p>
    </div>
    {@render previewButton(v.id, label)}
    {@render useButton(v.id, label, true)}
    {#if !isOriginal}
      <button
        type="button"
        onclick={() => remove(v, false)}
        aria-label="Delete the {v.accent_label} accent"
        class="shrink-0 w-11 h-11 flex items-center justify-center rounded-full text-gray-400
               hover:bg-gray-100 hover:text-danger transition-colors cursor-pointer"
      >
        <svg viewBox="0 0 16 16" class="w-4 h-4" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" /></svg>
      </button>
    {/if}
  </li>
{/snippet}

<div class="max-w-2xl flex flex-col gap-8">
  {#if loadError}
    <p class="text-[13.5px] text-danger" role="alert">{loadError}</p>
  {:else if !library}
    <p class="text-[13.5px] text-gray-400">Loading voices…</p>
  {:else}
    {#if !library.service.running}
      <p class="px-5 py-4 rounded-2xl bg-accent-soft text-[13.5px] text-gray-700" role="status">
        The local voice service is off. Start it in a terminal with
        <code class="font-mono text-sm">make dev-voice</code>, then reload this page. You can still record
        voices without it.
      </p>
    {:else if library.service.error}
      <p class="px-5 py-4 rounded-2xl bg-accent-soft text-[13.5px] text-gray-700" role="status">
        {library.service.error}
      </p>
    {:else if !library.service.ready}
      <p class="px-5 py-4 rounded-2xl bg-accent-soft text-[13.5px] text-gray-700" role="status">
        The voice models are loading. This takes about a minute after the service starts.
        <button type="button" onclick={load} class="font-semibold text-link cursor-pointer">Check Again</button>
      </p>
    {/if}

    <!-- Voices -->
    <section aria-labelledby="voices-title">
      <h2 id="voices-title" class="group-title">Voice on Calls</h2>
      <div role="radiogroup" aria-labelledby="voices-title" class="flex flex-col gap-4">
        <ul class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <li class="flex items-center gap-2 sm:gap-3 px-4 py-2.5">
            <div class="flex-1 min-w-0">
              <p class="text-[14.5px] font-medium truncate">Cartesia Voice</p>
              <p class="text-[12.5px] text-gray-500 truncate">The standard cloud voice. Needs Cartesia credits.</p>
            </div>
            {@render useButton(null, 'the Cartesia cloud voice', false)}
          </li>
        </ul>

        {#each library.voices as voice (voice.id)}
          {@const options = unusedAccents(voice)}
          <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div class="flex items-center gap-3 px-4 pt-3 pb-2">
              <h3 class="flex-1 min-w-0 text-[17px] font-semibold truncate">{voice.name}</h3>
              <button
                type="button"
                onclick={() => remove(voice, true)}
                class="min-h-9 px-3 rounded-xl text-[13.5px] font-semibold text-danger hover:bg-gray-100 transition-colors cursor-pointer"
              >
                Delete Voice
              </button>
            </div>
            <ul>
              {@render voiceRow(voice, true)}
              {#each voice.versions as version (version.id)}
                {@render voiceRow(version, false)}
              {/each}
            </ul>
            {#if options.length}
              <div class="flex flex-wrap items-center gap-3 px-4 py-3 border-t border-gray-200 bg-gray-50">
                <label class="flex-1 min-w-44">
                  <span class="sr-only">Accent to make for {voice.name}</span>
                  <select
                    bind:value={accentChoice[voice.id]}
                    disabled={!ready || making !== null}
                    class="w-full min-h-9 px-3 rounded-xl bg-white border border-gray-200 text-[14.5px] cursor-pointer disabled:opacity-50"
                  >
                    <option value="">Choose an accent</option>
                    {#each options as [key, label] (key)}
                      <option value={key}>{label}</option>
                    {/each}
                  </select>
                </label>
                <button
                  type="button"
                  onclick={() => makeAccent(voice)}
                  disabled={!ready || making !== null || !accentChoice[voice.id]}
                  class="min-h-9 px-4 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                         hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-default"
                >
                  {making?.voiceId === voice.id ? 'Making…' : 'Make Accent'}
                </button>
              </div>
            {/if}
          </div>
        {/each}
      </div>

      <div aria-live="polite">
        {#if making}
          <p class="mt-3 text-[12.5px] text-gray-600">
            Making the {library.accents[making.accent]} accent. This takes about 20 seconds.
          </p>
        {/if}
        {#if listError}
          <p class="mt-3 text-[12.5px] text-danger">{listError}</p>
        {/if}
      </div>
      <p class="mt-3 mx-5 text-[12.5px] text-gray-500">
        Local and Claude modes speak with the voice in use. Gemini always uses its own voice. A change
        applies to the next call.
      </p>
    </section>

    <!-- Record -->
    <section aria-labelledby="record-title">
      <h2 id="record-title" class="group-title">Add Your Voice</h2>
      <form onsubmit={save} novalidate class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
        <div class="px-5 pt-4 pb-4">
          <p class="text-[12.5px] font-medium text-gray-500">Read this aloud, in your normal voice</p>
          <blockquote class="mt-2 text-[17px] leading-snug font-medium text-gray-900">
            “{library.script}”
          </blockquote>
          <p class="mt-3 text-[12.5px] text-gray-500">
            Use a quiet room and hold the microphone close. Read all of it: {library.min_seconds} to
            {library.max_seconds} seconds.
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
          {#if recording}
            <button
              type="button"
              onclick={stop}
              class="min-h-9 px-5 rounded-xl bg-danger text-white text-[13.5px] font-semibold cursor-pointer"
            >
              Stop Recording
            </button>
            <span class="flex items-center gap-2 text-[14.5px] tabular-nums" aria-live="off">
              <span class="w-2.5 h-2.5 rounded-full bg-danger motion-safe:animate-pulse" aria-hidden="true"></span>
              {clock(elapsed)} / {clock(library.max_seconds)}
            </span>
          {:else}
            <button
              type="button"
              onclick={record}
              class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                     hover:bg-accent-hover transition-colors cursor-pointer"
            >
              {take ? 'Record Again' : 'Start Recording'}
            </button>
            <label
              class="min-h-9 px-4 flex items-center rounded-xl text-[13.5px] font-semibold text-link
                     hover:bg-gray-100 transition-colors cursor-pointer has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-[var(--focus)]"
            >
              Upload a File
              <input type="file" accept="audio/*" onchange={upload} class="sr-only" />
            </label>
          {/if}
        </div>

        {#if take}
          <div class="flex items-center gap-3 px-5 py-3 border-t border-gray-200">
            {@render playButton('take', takeUrl, 'your recording')}
            <p class="flex-1 text-[13.5px]">
              Your recording · {takeSeconds.toFixed(1)} s
              {#if takeSeconds < library.min_seconds}
                <span class="block text-[12.5px] text-danger">Too short. Read the whole script.</span>
              {/if}
            </p>
          </div>
          <label class="block px-5 pt-3 pb-3 border-t border-gray-200">
            <span class="block text-[12.5px] font-medium text-gray-500">Name</span>
            <input
              bind:value={name}
              maxlength="40"
              placeholder="Asha"
              class="w-full min-h-9 text-[14.5px] bg-transparent border-none outline-none placeholder:text-gray-400"
            />
          </label>
        {/if}

        <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
          <p class="flex-1 min-w-48 text-[12.5px]" aria-live="polite">
            {#if recordError}<span class="text-danger">{recordError}</span>{/if}
          </p>
          <button
            type="submit"
            disabled={!take || saving || takeSeconds < library.min_seconds}
            class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                   hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-default"
          >
            {saving ? 'Saving…' : 'Save Voice'}
          </button>
        </div>
      </form>
    </section>
  {/if}
</div>
