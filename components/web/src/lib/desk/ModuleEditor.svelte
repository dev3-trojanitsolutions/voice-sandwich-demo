<script lang="ts">
  import { untrack } from 'svelte';
  import {
    addModule,
    addSection,
    deleteModule,
    deleteSection,
    reorderSections,
    updateModule,
    updateSection,
    type KnowledgeModule,
    type ModuleKind,
    type Section,
  } from '../api';

  interface Props {
    // null: the form for a new module
    module: KnowledgeModule | null;
    canMoveUp: boolean;
    canMoveDown: boolean;
    onSaved: (module: KnowledgeModule) => void;
    onDeleted: () => void;
    onMove: (step: -1 | 1) => void;
    onCancel: () => void;
  }

  let { module, canMoveUp, canMoveDown, onSaved, onDeleted, onMove, onCancel }: Props = $props();

  const KINDS: { id: ModuleKind; label: string; detail: string }[] = [
    {
      id: 'menu',
      label: 'Menu',
      detail: 'Dishes and prices. The agent also lists these dishes when it takes the order.',
    },
    { id: 'notes', label: 'Notes', detail: 'Facts and policies, one topic per section.' },
    { id: 'qa', label: 'Q&A', detail: 'A question customers ask, and the answer to give.' },
  ];

  const FIELDS: Record<ModuleKind, { title: string; body: string; titleHint: string; bodyHint: string; help: string }> = {
    menu: {
      title: 'Category',
      body: 'Dishes',
      titleHint: 'Starters',
      bodyHint: 'Chicken 65: spicy fried chicken bites with curry leaves, ₹210.',
      help: 'One dish per line, as Name: description, price.',
    },
    notes: {
      title: 'Topic',
      body: 'What the agent should know',
      titleHint: 'Delivery',
      bodyHint: 'We deliver anywhere in Bangalore. Delivery takes 30 to 45 minutes.',
      help: 'Keep each section about one topic.',
    },
    qa: {
      title: 'Customer asks',
      body: 'Agent answers',
      titleHint: 'Do you deliver to Whitefield?',
      bodyHint: 'Yes. Whitefield is in our delivery area. Delivery takes about 45 minutes.',
      help: 'Write the answer the way the agent should say it.',
    },
  };

  // Module details form: open for a new module, or after "Edit Details"
  let editingDetails = $state(false);
  let name = $state('');
  let kind = $state<ModuleKind>('notes');
  let intro = $state('');
  let detailsError = $state('');
  let savingDetails = $state(false);

  // Section form: sectionId null adds a section, a number edits that one
  let sectionId = $state<number | null>(null);
  let title = $state('');
  let body = $state('');
  let sectionError = $state('');
  let sectionNotice = $state('');
  let savingSection = $state(false);

  let busy = $state(false);
  let actionError = $state('');

  let fields = $derived(FIELDS[module?.kind ?? 'notes']);

  // Reset the forms when another module opens. A save hands in a new object
  // for the same module, which must not reset them.
  $effect(() => {
    module?.id;
    untrack(resetForms);
  });

  function resetForms() {
    const current = module;
    editingDetails = current === null;
    name = current?.name ?? '';
    kind = current?.kind ?? 'notes';
    intro = current?.intro ?? '';
    detailsError = '';
    sectionId = null;
    title = '';
    body = '';
    sectionError = '';
    sectionNotice = '';
    actionError = '';
  }

  async function saveDetails(event: SubmitEvent) {
    event.preventDefault();
    detailsError = '';
    if (!name.trim()) {
      detailsError = 'Enter a name for the module.';
      return;
    }
    savingDetails = true;
    try {
      const saved = module
        ? await updateModule(module.id, name, kind, intro)
        : await addModule(name, kind, intro);
      editingDetails = false;
      onSaved(saved);
    } catch (e) {
      detailsError = (e as Error).message;
    } finally {
      savingDetails = false;
    }
  }

  function cancelDetails() {
    if (!module) {
      onCancel();
      return;
    }
    editingDetails = false;
    name = module.name;
    kind = module.kind;
    intro = module.intro;
    detailsError = '';
  }

  async function removeModule() {
    if (!module) return;
    const count = module.sections.length;
    const what = count === 1 ? '1 section' : `${count} sections`;
    if (!confirm(`Delete “${module.name}” and its ${what}? The agent stops using it.`)) return;
    busy = true;
    try {
      await deleteModule(module.id);
      onDeleted();
    } catch (e) {
      actionError = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  function startEdit(section: Section) {
    sectionId = section.id;
    title = section.title;
    body = section.body;
    sectionError = '';
    sectionNotice = '';
  }

  function resetSectionForm() {
    sectionId = null;
    title = '';
    body = '';
  }

  async function saveSection(event: SubmitEvent) {
    event.preventDefault();
    if (!module) return;
    sectionError = '';
    sectionNotice = '';
    if (!title.trim()) {
      sectionError = `Enter the ${fields.title.toLowerCase()}.`;
      return;
    }
    if (!body.trim()) {
      sectionError = `Enter the ${fields.body.toLowerCase()}.`;
      return;
    }
    savingSection = true;
    try {
      const saved =
        sectionId === null
          ? await addSection(module.id, title, body)
          : await updateSection(sectionId, title, body);
      sectionNotice = sectionId === null ? 'Added. The agent uses it from the next question.' : 'Changes saved.';
      resetSectionForm();
      onSaved(saved);
    } catch (e) {
      sectionError = (e as Error).message;
    } finally {
      savingSection = false;
    }
  }

  async function removeSection(section: Section) {
    if (!confirm(`Delete “${section.title}”? The agent stops using it.`)) return;
    busy = true;
    try {
      const saved = await deleteSection(section.id);
      if (sectionId === section.id) resetSectionForm();
      onSaved(saved);
    } catch (e) {
      actionError = (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function moveSection(index: number, step: -1 | 1) {
    if (!module) return;
    const ids = module.sections.map((s) => s.id);
    [ids[index], ids[index + step]] = [ids[index + step], ids[index]];
    busy = true;
    try {
      onSaved(await reorderSections(module.id, ids));
    } catch (e) {
      actionError = (e as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

{#snippet arrow(direction: 'up' | 'down', label: string, disabled: boolean, onclick: () => void)}
  <button
    {onclick}
    {disabled}
    aria-label={label}
    title={label}
    class="w-11 h-11 rounded-lg flex items-center justify-center text-gray-500
           hover:bg-gray-100 transition-colors cursor-pointer disabled:opacity-30 disabled:cursor-default"
  >
    <svg viewBox="0 0 12 12" class="w-3 h-3 {direction === 'down' ? 'rotate-180' : ''}" aria-hidden="true">
      <path d="M2 8l4-4 4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </button>
{/snippet}

<div class="flex flex-col gap-6">
  <!-- Module details -->
  {#if editingDetails}
    <form
      onsubmit={saveDetails}
      novalidate
      class="bg-white rounded-2xl border border-gray-200 overflow-hidden"
    >
      <h2 class="px-5 pt-4 text-[17px] font-semibold">{module ? 'Edit Module' : 'New Module'}</h2>
      <label class="block px-5 pt-3 pb-3">
        <span class="block text-[12.5px] font-medium text-gray-500">Name</span>
        <input
          bind:value={name}
          maxlength="60"
          placeholder="Offers"
          class="w-full min-h-9 text-[14.5px] bg-transparent border-none outline-none placeholder:text-gray-400"
        />
      </label>
      <fieldset class="px-5 py-3 border-t border-gray-200">
        <legend class="sr-only">Type</legend>
        <span class="block mb-2 text-[12.5px] font-medium text-gray-500" aria-hidden="true">Type</span>
        <div class="grid grid-cols-3 p-1 bg-gray-100 rounded-xl">
          {#each KINDS as k (k.id)}
            <label
              class="min-h-9 flex items-center justify-center rounded-[9px] text-[13.5px] font-semibold
                     cursor-pointer transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-[var(--focus)]
                     {kind === k.id ? 'bg-accent text-on-accent shadow-sm' : 'text-gray-600 hover:text-gray-900'}"
            >
              <input type="radio" bind:group={kind} value={k.id} class="sr-only" />
              {k.label}
            </label>
          {/each}
        </div>
        <p class="mt-2 text-[12.5px] text-gray-500">{KINDS.find((k) => k.id === kind)?.detail}</p>
      </fieldset>
      <label class="block px-5 pt-3 pb-4 border-t border-gray-200">
        <span class="block text-[12.5px] font-medium text-gray-500">Intro (optional)</span>
        <textarea
          bind:value={intro}
          rows="2"
          placeholder="All prices are in rupees and include GST."
          class="w-full mt-1 text-[14.5px] leading-snug bg-transparent border-none outline-none resize-y placeholder:text-gray-400"
        ></textarea>
      </label>
      <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
        <p class="flex-1 min-w-48 text-[12.5px]" aria-live="polite">
          {#if detailsError}<span class="text-danger">{detailsError}</span>{/if}
        </p>
        <button
          type="button"
          onclick={cancelDetails}
          class="min-h-9 px-4 rounded-xl text-[13.5px] font-semibold text-link hover:bg-gray-100 transition-colors cursor-pointer"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={savingDetails}
          class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                 hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-60"
        >
          {savingDetails ? 'Saving…' : module ? 'Save Changes' : 'Create Module'}
        </button>
      </div>
    </form>
  {:else if module}
    <header class="flex flex-wrap items-start gap-x-3 gap-y-2">
      <div class="flex-1 min-w-48">
        <h2 class="text-[19px] font-semibold leading-tight">{module.name}</h2>
        <p class="mt-0.5 text-[13.5px] text-gray-500">
          {KINDS.find((k) => k.id === module.kind)?.label} ·
          {module.sections.length === 1 ? '1 section' : `${module.sections.length} sections`}
        </p>
        {#if module.intro}
          <p class="mt-2 text-[13.5px] text-gray-600 whitespace-pre-line">{module.intro}</p>
        {/if}
      </div>
      <div class="flex items-center">
        {@render arrow('up', 'Move module up', !canMoveUp || busy, () => onMove(-1))}
        {@render arrow('down', 'Move module down', !canMoveDown || busy, () => onMove(1))}
        <button
          onclick={() => (editingDetails = true)}
          class="min-h-9 px-3 rounded-lg text-[13.5px] font-medium text-link hover:bg-gray-100 transition-colors cursor-pointer"
        >
          Edit
        </button>
        <button
          onclick={removeModule}
          disabled={busy}
          class="min-h-9 px-3 rounded-lg text-[13.5px] font-medium text-danger hover:bg-gray-100 transition-colors cursor-pointer"
        >
          Delete
        </button>
      </div>
    </header>
  {/if}

  {#if actionError}
    <p class="text-[13.5px] text-danger" role="alert">{actionError}</p>
  {/if}

  {#if module}
    <!-- Sections -->
    <section aria-label="Sections">
      <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
        {#if module.sections.length === 0}
          <p class="px-5 py-8 text-center text-[13.5px] text-gray-500">
            No sections yet. Add the first one below.
          </p>
        {:else}
          <ol>
            {#each module.sections as section, i (section.id)}
              <li
                class="px-5 py-4 border-t border-gray-200 first:border-t-0
                       {sectionId === section.id ? 'bg-accent-soft' : ''}"
              >
                <p class="text-[14.5px] font-medium">{section.title}</p>
                <p class="mt-1 text-[13.5px] text-gray-600 whitespace-pre-line">{section.body}</p>
                <div class="flex flex-wrap items-center justify-end mt-1 -mr-3">
                  {@render arrow('up', `Move “${section.title}” up`, i === 0 || busy, () => moveSection(i, -1))}
                  {@render arrow('down', `Move “${section.title}” down`, i === module.sections.length - 1 || busy, () => moveSection(i, 1))}
                  <button
                    onclick={() => startEdit(section)}
                    class="min-h-9 px-3 rounded-lg text-[13.5px] font-medium text-link hover:bg-gray-100 transition-colors cursor-pointer"
                  >
                    Edit
                  </button>
                  <button
                    onclick={() => removeSection(section)}
                    disabled={busy}
                    class="min-h-9 px-3 rounded-lg text-[13.5px] font-medium text-danger hover:bg-gray-100 transition-colors cursor-pointer"
                  >
                    Delete
                  </button>
                </div>
              </li>
            {/each}
          </ol>
        {/if}
      </div>
    </section>

    <!-- Add or edit a section -->
    <section aria-labelledby="section-form-title">
      <h3 id="section-form-title" class="group-title">
        {sectionId === null ? 'Add Section' : 'Edit Section'}
      </h3>
      <form
        onsubmit={saveSection}
        novalidate
        class="bg-white rounded-2xl border border-gray-200 overflow-hidden"
      >
        <label class="block px-5 pt-4 pb-3">
          <span class="block text-[12.5px] font-medium text-gray-500">{fields.title}</span>
          <input
            bind:value={title}
            maxlength="300"
            placeholder={fields.titleHint}
            class="w-full min-h-9 text-[14.5px] bg-transparent border-none outline-none placeholder:text-gray-400"
          />
        </label>
        <label class="block px-5 pt-3 pb-4 border-t border-gray-200">
          <span class="block text-[12.5px] font-medium text-gray-500">{fields.body}</span>
          <textarea
            bind:value={body}
            maxlength="4000"
            rows="5"
            placeholder={fields.bodyHint}
            class="w-full mt-1 text-[14.5px] leading-snug bg-transparent border-none outline-none resize-y placeholder:text-gray-400"
          ></textarea>
        </label>
        <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
          <p class="flex-1 min-w-48 text-[12.5px]" aria-live="polite">
            {#if sectionError}
              <span class="text-danger">{sectionError}</span>
            {:else if sectionNotice}
              <span class="text-success">{sectionNotice}</span>
            {:else}
              <span class="text-gray-400">{fields.help}</span>
            {/if}
          </p>
          {#if sectionId !== null}
            <button
              type="button"
              onclick={resetSectionForm}
              class="min-h-9 px-4 rounded-xl text-[13.5px] font-semibold text-link hover:bg-gray-100 transition-colors cursor-pointer"
            >
              Cancel
            </button>
          {/if}
          <button
            type="submit"
            disabled={savingSection}
            class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                   hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-60"
          >
            {savingSection ? 'Saving…' : sectionId === null ? 'Add Section' : 'Save Changes'}
          </button>
        </div>
      </form>
    </section>
  {/if}
</div>
