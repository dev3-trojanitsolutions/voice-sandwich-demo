<script lang="ts">
  import { onMount } from 'svelte';
  import {
    getModules,
    reorderModules,
    testKnowledge,
    type KnowledgeMatch,
    type KnowledgeModule,
  } from '../api';
  import ModuleEditor from './ModuleEditor.svelte';

  interface Props {
    selectedId: number | null;
  }

  let { selectedId }: Props = $props();

  const KIND_LABELS = { menu: 'Menu', notes: 'Notes', qa: 'Q&A' };

  let modules = $state<KnowledgeModule[]>([]);
  let loaded = $state(false);
  let listError = $state('');
  let creating = $state(false);

  let testQuestion = $state('');
  let testing = $state(false);
  let testError = $state('');
  let matches = $state<KnowledgeMatch[] | null>(null);

  let selected = $derived(modules.find((m) => m.id === selectedId) ?? null);
  let selectedIndex = $derived(modules.findIndex((m) => m.id === selectedId));
  let showEditor = $derived(creating || selected !== null);

  // Opening a module closes the new module form
  $effect(() => {
    if (selectedId !== null) creating = false;
  });

  async function loadModules() {
    try {
      modules = await getModules();
      listError = '';
    } catch (e) {
      listError = `Can't load modules. ${(e as Error).message}`;
    } finally {
      loaded = true;
    }
  }

  function startCreate() {
    creating = true;
    if (selectedId !== null) location.hash = '#training';
  }

  function onSaved(saved: KnowledgeModule) {
    const index = modules.findIndex((m) => m.id === saved.id);
    if (index === -1) {
      modules = [...modules, saved];
      location.hash = `#training/${saved.id}`;
    } else {
      modules[index] = saved;
    }
    matches = null;
  }

  function onDeleted() {
    modules = modules.filter((m) => m.id !== selectedId);
    matches = null;
    location.hash = '#training';
  }

  async function onMove(step: -1 | 1) {
    const ids = modules.map((m) => m.id);
    const i = selectedIndex;
    [ids[i], ids[i + step]] = [ids[i + step], ids[i]];
    try {
      modules = await reorderModules(ids);
    } catch (e) {
      listError = (e as Error).message;
    }
  }

  async function runTest(event: SubmitEvent) {
    event.preventDefault();
    if (!testQuestion.trim()) return;
    testing = true;
    testError = '';
    try {
      matches = await testKnowledge(testQuestion);
    } catch (e) {
      testError = (e as Error).message;
      matches = null;
    } finally {
      testing = false;
    }
  }

  onMount(loadModules);
</script>

<p class="max-w-3xl mb-6 text-[13.5px] text-gray-600">
  Everything the agent knows about the shop lives here: the menu, the FAQ, allergens and any
  module you add. Every voice model searches it while it talks, and uses a change from the next
  question.
</p>

<!-- Test -->
<section aria-labelledby="test-title" class="max-w-3xl mb-8">
  <h2 id="test-title" class="group-title">Test a Question</h2>
  <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
    <form onsubmit={runTest} class="flex items-center gap-3 px-5 py-3">
      <input
        bind:value={testQuestion}
        type="search"
        aria-label="Question to test"
        placeholder="Ask what a customer would ask"
        class="flex-1 min-w-0 min-h-9 text-[14.5px] bg-transparent border-none outline-none placeholder:text-gray-400"
      />
      <button
        type="submit"
        disabled={testing || !testQuestion.trim()}
        class="min-h-9 px-4 rounded-xl bg-gray-100 text-[13.5px] font-semibold text-link
               hover:bg-gray-200 transition-colors cursor-pointer disabled:opacity-50"
      >
        {testing ? 'Testing…' : 'Test'}
      </button>
    </form>

    <div aria-live="polite">
      {#if testError}
        <p class="px-5 pb-4 text-[12.5px] text-danger">{testError}</p>
      {:else if matches}
        {#if matches.length === 0}
          <p class="px-5 pb-4 text-[13.5px] text-gray-500">The knowledge base is empty.</p>
        {:else}
          <p class="px-5 py-2 border-t border-gray-200 text-[12.5px] text-gray-500">
            The agent gets these {matches.length} results, best match first.
          </p>
          <ol>
            {#each matches as match, i (match.id)}
              <li class="px-5 py-3 border-t border-gray-200">
                <div class="flex items-center gap-2 text-[12.5px]">
                  <a
                    href="#training/{match.module_id}"
                    class="px-2 py-0.5 rounded-full font-semibold bg-accent-soft text-link"
                  >
                    {match.source}
                  </a>
                  {#if i === 0}<span class="text-gray-500">Best match</span>{/if}
                </div>
                <p class="mt-1.5 text-[13.5px] text-gray-900 whitespace-pre-line line-clamp-4">
                  {match.text}
                </p>
              </li>
            {/each}
          </ol>
        {/if}
      {/if}
    </div>
  </div>
</section>

<div class="lg:grid lg:grid-cols-[minmax(240px,300px)_1fr] lg:gap-6 lg:items-start">
  <!-- Modules -->
  <section aria-labelledby="modules-title" class={showEditor ? 'hidden lg:block' : ''}>
    <h2 id="modules-title" class="group-title">Modules</h2>
    <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
      {#if listError}
        <p class="px-5 py-6 text-[13.5px] text-danger" role="alert">{listError}</p>
      {:else if !loaded}
        <p class="px-5 py-6 text-[13.5px] text-gray-400">Loading…</p>
      {:else}
        <ul>
          {#each modules as m (m.id)}
            {@const current = m.id === selectedId}
            <li class="border-b border-gray-200">
              <a
                href="#training/{m.id}"
                aria-current={current ? 'true' : undefined}
                class="flex items-center gap-3 min-h-12 px-4 py-2.5 transition-colors
                       {current ? 'bg-accent-soft' : 'hover:bg-gray-100'}"
              >
                <span class="flex-1 min-w-0">
                  <span class="block text-[14.5px] font-medium truncate">{m.name}</span>
                  <span class="block text-[12.5px] text-gray-500">
                    {KIND_LABELS[m.kind]} · {m.sections.length === 1 ? '1 section' : `${m.sections.length} sections`}
                  </span>
                </span>
                <svg class="w-3 h-3 shrink-0 text-gray-400" viewBox="0 0 12 12" aria-hidden="true">
                  <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </a>
            </li>
          {:else}
            <li class="px-5 py-6 text-[13.5px] text-gray-500 border-b border-gray-200">
              No modules. The agent has nothing to look up.
            </li>
          {/each}
        </ul>
        <button
          onclick={startCreate}
          class="w-full min-h-12 px-4 text-left text-[14.5px] font-medium text-link
                 hover:bg-gray-100 transition-colors cursor-pointer
                 {creating ? 'bg-accent-soft' : ''}"
        >
          + New Module
        </button>
      {/if}
    </div>
  </section>

  <!-- Editor -->
  <div class={showEditor ? '' : 'hidden lg:block'}>
    {#if showEditor}
      <a
        href="#training"
        onclick={() => (creating = false)}
        class="lg:hidden inline-flex items-center min-h-9 mb-2 text-[14.5px] text-link"
      >
        ‹ Modules
      </a>
      <ModuleEditor
        module={creating ? null : selected}
        canMoveUp={selectedIndex > 0}
        canMoveDown={selectedIndex !== -1 && selectedIndex < modules.length - 1}
        {onSaved}
        {onDeleted}
        {onMove}
        onCancel={() => (creating = false)}
      />
    {:else}
      <div
        class="hidden lg:flex items-center justify-center h-64 mt-7 rounded-2xl border border-dashed
               border-gray-300 text-[13.5px] text-gray-400"
      >
        Choose a module to edit it.
      </div>
    {/if}
  </div>
</div>
