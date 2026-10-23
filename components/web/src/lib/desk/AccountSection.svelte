<script lang="ts">
  import { changePassword, type User } from '../api';

  let { me }: { me: User } = $props();

  let current = $state('');
  let next = $state('');
  let repeat = $state('');
  let error = $state('');
  let notice = $state('');
  let saving = $state(false);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    notice = '';
    if (!current || !next) {
      error = 'Enter your current and new password.';
      return;
    }
    if (next !== repeat) {
      error = "The new passwords don't match.";
      return;
    }
    saving = true;
    try {
      await changePassword(current, next);
      notice = 'Password changed. Your other devices are logged out.';
      current = next = repeat = '';
    } catch (e) {
      error = (e as Error).message;
    } finally {
      saving = false;
    }
  }
</script>

<div class="max-w-2xl">
  <section aria-labelledby="me-title" class="mb-8">
    <h2 id="me-title" class="group-title">Logged In As</h2>
    <div class="flex items-center gap-4 px-5 py-4 bg-white rounded-2xl border border-gray-200">
      <span
        class="w-12 h-12 shrink-0 rounded-full bg-accent-soft text-link
               flex items-center justify-center text-[17px] font-semibold"
        aria-hidden="true"
      >
        {me.name.charAt(0).toUpperCase()}
      </span>
      <span class="flex-1 min-w-0">
        <span class="block text-[14.5px] font-medium truncate">{me.name}</span>
        <span class="block text-[13.5px] text-gray-500 truncate">{me.username} · {me.role_name}</span>
      </span>
      <a
        href="/logout/"
        class="flex items-center min-h-9 px-4 rounded-xl text-[13.5px] font-medium text-danger
               hover:bg-gray-100 transition-colors"
      >
        Log Out
      </a>
    </div>
  </section>

  <section aria-labelledby="password-title">
    <h2 id="password-title" class="group-title">Change Password</h2>
    <form
      onsubmit={submit}
      novalidate
      class="bg-white rounded-2xl border border-gray-200 overflow-hidden"
    >
      <!-- For password managers -->
      <input type="text" value={me.username} autocomplete="username" hidden readonly />
      <label class="field">
        <span class="field-label">Current</span>
        <input bind:value={current} type="password" autocomplete="current-password" class="field-input" />
      </label>
      <label class="field border-t border-gray-200">
        <span class="field-label">New</span>
        <input
          bind:value={next}
          type="password"
          autocomplete="new-password"
          placeholder="At least 4 characters"
          class="field-input"
        />
      </label>
      <label class="field border-t border-gray-200">
        <span class="field-label">Repeat</span>
        <input bind:value={repeat} type="password" autocomplete="new-password" class="field-input" />
      </label>
      <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
        <p class="flex-1 min-w-48 text-[12.5px]" aria-live="polite">
          {#if error}
            <span class="text-danger">{error}</span>
          {:else if notice}
            <span class="text-success">{notice}</span>
          {/if}
        </p>
        <button
          type="submit"
          disabled={saving}
          class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                 hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Change Password'}
        </button>
      </div>
    </form>
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
