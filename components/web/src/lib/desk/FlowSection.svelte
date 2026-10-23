<script lang="ts">
  import { onMount } from 'svelte';
  import { getFlow, resetFlow, saveFlow, type Flow, type FlowStep } from '../api';

  const LAST_KEY = 'otp';
  const MAX_STEPS = 12;

  let saved = $state<Flow | null>(null);
  let draft = $state<FlowStep[]>([]);
  let loadError = $state('');
  let saveError = $state('');
  let notice = $state('');
  let saving = $state(false);
  let openKey = $state<string | null>(null);

  // New custom step
  let newLabel = $state('');
  let newAsk = $state('');
  let newNotes = $state('');
  let newChoices = $state('');
  let newRequired = $state(true);
  let addError = $state('');

  let dirty = $derived(saved !== null && JSON.stringify(strip(draft)) !== JSON.stringify(strip(saved.steps)));

  function strip(steps: FlowStep[]) {
    return steps.map(({ key, kind, label, ask, notes, required, choices }) => ({
      key, kind, label, ask, notes, required, choices,
    }));
  }

  function load(flow: Flow) {
    saved = flow;
    draft = structuredClone(strip(flow.steps));
  }

  async function save() {
    saving = true;
    saveError = '';
    notice = '';
    try {
      load(await saveFlow(draft));
      openKey = null;
      notice = 'Flow saved. It applies from the next call.';
    } catch (e) {
      saveError = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  function discard() {
    if (saved) load(saved);
    openKey = null;
    saveError = '';
  }

  async function reset() {
    if (!confirm('Go back to the default flow? Custom steps are removed.')) return;
    saving = true;
    try {
      load(await resetFlow());
      openKey = null;
      notice = 'Default flow restored.';
    } catch (e) {
      saveError = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  function move(index: number, step: -1 | 1) {
    [draft[index], draft[index + step]] = [draft[index + step], draft[index]];
    notice = '';
  }

  function remove(index: number) {
    draft.splice(index, 1);
    notice = '';
  }

  function slug(label: string) {
    return label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 40);
  }

  function parseChoices(text: string): string[] {
    return text.split(',').map((c) => c.trim()).filter(Boolean);
  }

  function addStep(event: SubmitEvent) {
    event.preventDefault();
    addError = '';
    const key = slug(newLabel);
    if (!newLabel.trim() || !key) {
      addError = 'Enter a name for the step.';
      return;
    }
    if (!newAsk.trim()) {
      addError = 'Enter what the agent asks.';
      return;
    }
    if (draft.some((s) => s.key === key)) {
      addError = 'A step with this name is already in the flow.';
      return;
    }
    if (draft.length >= MAX_STEPS) {
      addError = `A flow can have at most ${MAX_STEPS} steps.`;
      return;
    }
    // New steps go just before the last step (OTP)
    draft.splice(draft.length - 1, 0, {
      key,
      kind: 'custom',
      label: newLabel.trim(),
      ask: newAsk.trim(),
      notes: newNotes.trim(),
      required: newRequired,
      choices: parseChoices(newChoices),
    });
    newLabel = newAsk = newNotes = newChoices = '';
    newRequired = true;
    notice = '';
  }

  onMount(() => {
    getFlow()
      .then(load)
      .catch((e) => (loadError = `Can't load the flow. ${(e as Error).message}`));
  });
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

<div class="max-w-2xl">
  <p class="mb-6 text-[13.5px] text-gray-600">
    The steps the agent asks for, in order. Move a step to change when it is asked, or add your
    own question. OTP always comes last, because it confirms the order.
  </p>

  {#if loadError}
    <p class="text-[13.5px] text-danger" role="alert">{loadError}</p>
  {:else if !saved}
    <p class="text-[13.5px] text-gray-400">Loading…</p>
  {:else}
    <!-- Steps -->
    <section aria-labelledby="steps-title" class="mb-8">
      <div class="flex items-baseline justify-between">
        <h2 id="steps-title" class="group-title">Steps</h2>
        {#if !saved.is_default}
          <button
            onclick={reset}
            disabled={saving}
            class="mb-2 text-[12.5px] font-medium text-link cursor-pointer"
          >
            Reset to Default
          </button>
        {/if}
      </div>
      <ol class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
        {#each draft as step, i (step.key)}
          {@const last = step.key === LAST_KEY}
          {@const open = openKey === step.key}
          <li class="border-t border-gray-200 first:border-t-0">
            <div class="flex items-start gap-3 px-4 py-3">
              <span
                class="w-8 h-8 mt-1.5 shrink-0 rounded-full flex items-center justify-center text-[13.5px] font-semibold
                       {step.kind === 'custom' ? 'bg-accent text-on-accent' : 'bg-accent-soft text-link'}"
                aria-hidden="true"
              >
                {i + 1}
              </span>
              <div class="flex-1 min-w-0 pt-1">
                <p class="flex flex-wrap items-center gap-x-2 text-[14.5px] font-medium">
                  {step.label}
                  <span class="text-[12.5px] font-normal text-gray-400">
                    {step.kind === 'custom' ? (step.required ? 'Custom' : 'Custom · Optional') : 'Built-in'}{last ? ' · Always last' : ''}
                  </span>
                </p>
                <p class="mt-0.5 text-[13.5px] text-gray-600">“{step.ask}”</p>
                {#if step.choices.length}
                  <p class="flex flex-wrap gap-1.5 mt-1.5">
                    {#each step.choices as choice (choice)}
                      <span class="px-2 py-0.5 rounded-full bg-gray-100 text-[12.5px] text-gray-600">{choice}</span>
                    {/each}
                  </p>
                {/if}
              </div>
              <div class="flex items-center shrink-0 -mr-2">
                {@render arrow('up', `Move “${step.label}” up`, last || i === 0, () => move(i, -1))}
                {@render arrow('down', `Move “${step.label}” down`, last || i >= draft.length - 2, () => move(i, 1))}
                <button
                  onclick={() => (openKey = open ? null : step.key)}
                  aria-expanded={open}
                  class="min-h-9 px-3 rounded-lg text-[13.5px] font-medium text-link hover:bg-gray-100 transition-colors cursor-pointer"
                >
                  {open ? 'Done' : 'Edit'}
                </button>
              </div>
            </div>

            {#if open}
              <div class="px-4 pb-4 pl-[60px] flex flex-col gap-3">
                <label class="block">
                  <span class="block text-[12.5px] font-medium text-gray-500">Name</span>
                  <input bind:value={step.label} maxlength="60" class="input" />
                </label>
                <label class="block">
                  <span class="block text-[12.5px] font-medium text-gray-500">The agent asks</span>
                  <input bind:value={step.ask} maxlength="300" class="input" />
                </label>
                <label class="block">
                  <span class="block text-[12.5px] font-medium text-gray-500">Extra instructions (optional)</span>
                  <textarea bind:value={step.notes} rows="3" class="input py-2 resize-y"></textarea>
                </label>
                {#if step.kind === 'custom'}
                  <label class="block">
                    <span class="block text-[12.5px] font-medium text-gray-500">Choices, separated by commas (optional)</span>
                    <input
                      value={step.choices.join(', ')}
                      oninput={(e) => (step.choices = parseChoices(e.currentTarget.value))}
                      placeholder="Mild, Medium, Hot"
                      class="input"
                    />
                  </label>
                  <label class="flex items-center justify-between min-h-9">
                    <span class="text-[13.5px]">Required</span>
                    <input type="checkbox" bind:checked={step.required} class="switch" />
                  </label>
                  <button
                    onclick={() => remove(i)}
                    class="self-start min-h-9 -ml-3 px-3 rounded-lg text-[13.5px] font-medium text-danger hover:bg-gray-100 transition-colors cursor-pointer"
                  >
                    Remove Step
                  </button>
                {/if}
              </div>
            {/if}
          </li>
        {/each}
      </ol>

      <div class="flex flex-wrap items-center gap-3 mt-3" aria-live="polite">
        <p class="flex-1 min-w-48 text-[12.5px]">
          {#if saveError}
            <span class="text-danger">{saveError}</span>
          {:else if dirty}
            <span class="text-gray-600">You have unsaved changes.</span>
          {:else if notice}
            <span class="text-success">{notice}</span>
          {/if}
        </p>
        {#if dirty}
          <button
            onclick={discard}
            class="min-h-9 px-4 rounded-xl text-[13.5px] font-semibold text-link hover:bg-gray-100 transition-colors cursor-pointer"
          >
            Discard
          </button>
          <button
            onclick={save}
            disabled={saving}
            class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                   hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-60"
          >
            {saving ? 'Saving…' : 'Save Flow'}
          </button>
        {/if}
      </div>
    </section>

    <!-- Add step -->
    <section aria-labelledby="add-step-title" class="mb-8">
      <h2 id="add-step-title" class="group-title">Add Step</h2>
      <form onsubmit={addStep} novalidate class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
        <label class="block px-5 pt-4 pb-3">
          <span class="block text-[12.5px] font-medium text-gray-500">Name</span>
          <input
            bind:value={newLabel}
            maxlength="60"
            placeholder="Spice level"
            class="w-full min-h-9 text-[14.5px] bg-transparent border-none outline-none placeholder:text-gray-400"
          />
        </label>
        <label class="block px-5 py-3 border-t border-gray-200">
          <span class="block text-[12.5px] font-medium text-gray-500">The agent asks</span>
          <input
            bind:value={newAsk}
            maxlength="300"
            placeholder="How spicy would you like your food: mild, medium or hot?"
            class="w-full min-h-9 text-[14.5px] bg-transparent border-none outline-none placeholder:text-gray-400"
          />
        </label>
        <label class="block px-5 py-3 border-t border-gray-200">
          <span class="block text-[12.5px] font-medium text-gray-500">Choices, separated by commas (optional)</span>
          <input
            bind:value={newChoices}
            placeholder="Mild, Medium, Hot"
            class="w-full min-h-9 text-[14.5px] bg-transparent border-none outline-none placeholder:text-gray-400"
          />
        </label>
        <label class="block px-5 py-3 border-t border-gray-200">
          <span class="block text-[12.5px] font-medium text-gray-500">Extra instructions (optional)</span>
          <input
            bind:value={newNotes}
            placeholder="Mention that Hot is very spicy."
            class="w-full min-h-9 text-[14.5px] bg-transparent border-none outline-none placeholder:text-gray-400"
          />
        </label>
        <label class="flex items-center justify-between min-h-11 px-5 border-t border-gray-200">
          <span class="text-[14.5px]">Required</span>
          <input type="checkbox" bind:checked={newRequired} class="switch" />
        </label>
        <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
          <p class="flex-1 min-w-48 text-[12.5px]" aria-live="polite">
            {#if addError}
              <span class="text-danger">{addError}</span>
            {:else}
              <span class="text-gray-400">The step is added before OTP. Save the flow to use it.</span>
            {/if}
          </p>
          <button
            type="submit"
            class="min-h-9 px-5 rounded-xl bg-gray-100 text-[13.5px] font-semibold text-link
                   hover:bg-gray-200 transition-colors cursor-pointer"
          >
            Add Step
          </button>
        </div>
      </form>
    </section>

    <!-- What the agent gets -->
    <section aria-labelledby="preview-title">
      <h2 id="preview-title" class="group-title">What the Agent Follows</h2>
      <div class="bg-white rounded-2xl border border-gray-200 px-5 py-4">
        <p class="text-[12.5px] text-gray-500">The saved flow, as the agent reads it.</p>
        <p class="mt-3 text-[13.5px]"><span class="font-semibold">Greeting:</span> “{saved.greeting}”</p>
        <pre class="mt-3 text-[12.5px] leading-relaxed text-gray-600 whitespace-pre-wrap font-mono">{saved.prompt}</pre>
      </div>
    </section>
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

  .switch:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }

  @media (prefers-reduced-motion: reduce) {
    .switch,
    .switch::after {
      transition: none;
    }
  }
</style>
