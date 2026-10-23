<script lang="ts">
  import { onMount } from 'svelte';
  import { brand, loadBrand } from '../brand.svelte';
  import BrandMark from '../components/BrandMark.svelte';
  import { getMe, login } from '../api';

  let username = $state('');
  let password = $state('');
  let showPassword = $state(false);
  let error = $state('');
  let busy = $state(false);

  // Only a page of this site ("//host" or "/\host" would be another site),
  // and not the login or logout page again
  function nextPage(): string {
    const next = new URLSearchParams(location.search).get('next') ?? '';
    const local = next.startsWith('/') && !next.startsWith('//') && !next.includes('\\');
    const auth = next.startsWith('/login') || next.startsWith('/logout');
    return local && !auth ? next : '/desk/';
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = '';
    if (!username.trim() || !password) {
      error = 'Enter your username and password.';
      return;
    }
    busy = true;
    try {
      await login(username, password);
      location.replace(nextPage());
    } catch (e) {
      error = (e as Error).message;
      password = '';
    } finally {
      busy = false;
    }
  }

  $effect(() => {
    document.title = `Log In · ${brand.current.name}`;
  });

  onMount(() => {
    loadBrand();
    // Already logged in: go straight to the desk
    getMe()
      .then(() => location.replace(nextPage()))
      .catch(() => {});
  });
</script>

<div class="login min-h-screen grid bg-white">
  <main class="flex flex-col justify-between gap-10 min-h-screen px-6 py-7 md:px-14 md:py-10">
    <p class="text-[17px] font-semibold tracking-tight">
      <BrandMark size={30} />
    </p>

    <div class="w-full max-w-[380px] self-center flex flex-col gap-7">
      <div class="flex flex-col gap-2">
        <h1 class="text-[30px] font-semibold tracking-[-0.035em] leading-[1.1]">Welcome back</h1>
        <p class="text-[14.5px] text-gray-500">Log in to the desk and the order page.</p>
      </div>

      <form onsubmit={submit} novalidate class="flex flex-col gap-4">
        {#if error}
          <div
            role="alert"
            class="flex gap-2.5 items-start px-3 py-[11px] rounded-[10px] bg-danger/10 text-danger
                   text-[13.5px] leading-[1.45]"
          >
            <i class="ph ph-warning-circle text-[17px] shrink-0 mt-px" aria-hidden="true"></i>
            <span>{error}</span>
          </div>
        {/if}

        <label class="flex flex-col gap-1.5">
          <span class="text-[13px] font-medium">Username</span>
          <input
            bind:value={username}
            name="username"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            placeholder="Your username"
            class="input"
          />
        </label>

        <label class="flex flex-col gap-1.5">
          <span class="text-[13px] font-medium">Password</span>
          <span class="relative block">
            <input
              bind:value={password}
              name="password"
              type={showPassword ? 'text' : 'password'}
              autocomplete="current-password"
              placeholder="••••••••"
              class="input w-full pr-11"
            />
            <button
              type="button"
              onclick={() => (showPassword = !showPassword)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              class="absolute right-[5px] top-[5px] w-8 h-8 grid place-items-center rounded-lg
                     text-gray-500 hover:bg-gray-100 cursor-pointer"
            >
              <i class="ph {showPassword ? 'ph-eye-slash' : 'ph-eye'} text-[17px]" aria-hidden="true"></i>
            </button>
          </span>
        </label>

        <button
          type="submit"
          disabled={busy}
          class="h-11 flex items-center justify-center gap-2 rounded-[10px] bg-accent text-on-accent
                 text-[14.5px] font-medium hover:bg-accent-hover transition-colors cursor-pointer
                 disabled:opacity-60 disabled:cursor-default"
        >
          {#if busy}
            <i class="ph ph-circle-notch text-[17px] animate-spin" aria-hidden="true"></i>
          {/if}
          {busy ? 'Logging In…' : 'Log In'}
        </button>
      </form>

      <div
        class="flex items-center gap-2.5 px-3.5 py-3 rounded-[10px] bg-gray-50 border border-gray-200
               text-[13px] text-gray-500"
      >
        <i class="ph ph-info text-[16px] text-gray-400" aria-hidden="true"></i>
        <span>No account? Ask an admin to add you in Users.</span>
      </div>
    </div>

    <p class="text-[12.5px] text-gray-400">© {new Date().getFullYear()} {brand.current.name}</p>
  </main>

  <aside
    class="showcase relative m-2.5 rounded-[22px] overflow-hidden flex-col justify-between gap-10 p-12
           text-white"
    aria-hidden="true"
  >
    <div class="flex flex-col gap-3.5 max-w-[460px]">
      <span
        class="inline-flex self-start items-center gap-2 h-7 px-3 rounded-full border border-white/15
               text-[12.5px] text-white/80"
      >
        <span class="live-dot w-1.5 h-1.5 rounded-full bg-[#ff5b1f]"></span>
        A voice agent for {brand.current.name}
      </span>
      <p class="text-[40px] font-semibold tracking-[-0.04em] leading-[1.05]">
        Every call answered.<br /><span class="text-white/50">Every order taken.</span>
      </p>
      <p class="text-[15px] leading-[1.55] text-white/65">
        The agent picks up, follows the flow you set, and answers from your own menu, delivery
        areas and knowledge.
      </p>
    </div>

    <div
      class="self-stretch max-w-[480px] w-full rounded-[18px] bg-white/5 border border-white/10
             backdrop-blur-md p-[18px] flex flex-col gap-3.5"
    >
      <div class="flex items-center gap-3">
        <span class="w-9 h-9 rounded-full grid place-items-center bg-[#ff5b1f] font-semibold text-[14px]">
          {brand.current.icon || brand.current.name.charAt(0)}
        </span>
        <div class="flex-1 min-w-0">
          <p class="text-[14px] font-medium truncate">{brand.current.name} · Order line</p>
          <p class="font-mono text-[11.5px] text-white/55">live</p>
        </div>
        <span class="font-mono text-[12px] text-white/70">02:14</span>
      </div>
      <div class="flex items-center gap-[3px] h-11">
        {#each [8, 14, 22, 30, 18, 26, 36, 24, 14, 20, 32, 40, 28, 18, 10, 16, 26, 34, 22, 12, 8, 14, 24, 18, 10] as h, i (i)}
          <span
            class="w-[3px] rounded-full {i > 9 && i < 15 ? 'bg-[#ff5b1f]' : 'bg-white/40'}"
            style:height="{h}px"
          ></span>
        {/each}
      </div>
      <div class="flex flex-col gap-2 text-[13.5px] leading-[1.45]">
        <p class="self-start max-w-[85%] px-3 py-[9px] rounded-[12px_12px_12px_4px] bg-white/10">
          Is that for pickup or delivery?
        </p>
        <p class="self-end max-w-[85%] px-3 py-[9px] rounded-[12px_12px_4px_12px] bg-white/15">
          Delivery, please.
        </p>
        <p class="self-start max-w-[85%] px-3 py-[9px] rounded-[12px_12px_12px_4px] bg-white/10">
          Sure. What's your pincode?
        </p>
      </div>
    </div>
  </aside>
</div>

<style>
  .login {
    grid-template-columns: 1fr;
  }

  .showcase {
    display: none;
    background-color: #0b0b0c;
    background-image:
      radial-gradient(120% 70% at 85% 0%, rgb(255 91 31 / 0.22), transparent 60%),
      radial-gradient(80% 60% at 0% 100%, rgb(255 255 255 / 0.06), transparent 60%);
  }

  @media (min-width: 960px) {
    .login {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr);
    }

    .showcase {
      display: flex;
    }
  }

  .input {
    height: 42px;
    padding: 0 14px;
    border: 1px solid var(--g300);
    border-radius: 10px;
    background: var(--surface);
    font-size: 14.5px;
    color: var(--g900);
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.03);
    outline: none;
  }

  .input::placeholder {
    color: var(--g400);
  }

  .input:focus {
    border-color: var(--brand);
    box-shadow: 0 0 0 3px rgb(255 91 31 / 0.15);
  }

  .live-dot {
    animation: pulse-dot 2s infinite;
  }
</style>
