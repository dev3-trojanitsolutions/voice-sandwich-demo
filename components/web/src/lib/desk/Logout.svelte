<script lang="ts">
  import { onMount } from 'svelte';
  import { brand, loadBrand } from '../brand.svelte';
  import BrandMark from '../components/BrandMark.svelte';
  import { logout } from '../api';

  // Opening this page logs out. The server forgets the session, and the
  // cookie is removed, so the back button can't open the desk again.
  let done = $state(false);
  let error = $state('');

  $effect(() => {
    document.title = `Logged Out · ${brand.current.name}`;
  });

  onMount(() => {
    loadBrand();
    logout()
      .then(() => (done = true))
      .catch((e) => (error = `Can't log out. ${(e as Error).message}`));
  });
</script>

<main class="min-h-screen flex flex-col justify-between gap-10 px-6 py-7 md:px-14 md:py-10 bg-white">
  <p class="text-[17px] font-semibold tracking-tight">
    <BrandMark size={30} />
  </p>

  <div class="w-full max-w-[380px] self-center flex flex-col gap-6" role="status">
    {#if error}
      <span class="w-12 h-12 rounded-[14px] grid place-items-center bg-danger/10">
        <i class="ph ph-warning-circle text-[24px] text-danger" aria-hidden="true"></i>
      </span>
      <div class="flex flex-col gap-2">
        <h1 class="text-[30px] font-semibold tracking-[-0.035em] leading-[1.1]">Not logged out</h1>
        <p class="text-[14.5px] text-danger">{error}</p>
      </div>
    {:else if done}
      <span class="w-12 h-12 rounded-[14px] grid place-items-center bg-accent-soft">
        <i class="ph ph-sign-out text-[24px] text-link" aria-hidden="true"></i>
      </span>
      <div class="flex flex-col gap-2">
        <h1 class="text-[30px] font-semibold tracking-[-0.035em] leading-[1.1]">You're logged out</h1>
        <p class="text-[14.5px] text-gray-500 leading-normal">
          Log in again to use the order page and the desk.
        </p>
      </div>
    {:else}
      <p class="flex items-center gap-2 text-[14.5px] text-gray-400">
        <i class="ph ph-circle-notch text-[17px] animate-spin" aria-hidden="true"></i>
        Logging out…
      </p>
    {/if}

    {#if done || error}
      <a
        href="/login/"
        class="self-start h-[42px] px-[18px] flex items-center rounded-[10px] bg-accent text-on-accent
               text-[14px] font-medium hover:bg-accent-hover transition-colors"
      >
        Log In Again
      </a>
    {/if}
  </div>

  <p class="text-[12.5px] text-gray-400">© {new Date().getFullYear()} {brand.current.name}</p>
</main>
