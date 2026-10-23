<script lang="ts">
  import { onMount } from 'svelte';
  import { session, formattedTime } from '../stores';
  import { getSettings, PIPELINE_NAMES } from '../api';
  import { brand, loadBrand } from '../brand.svelte';
  import BrandMark from './BrandMark.svelte';

  let mode = $state('');

  $effect(() => {
    document.title = brand.current.name;
  });

  // Show which voice mode the next session uses
  onMount(async () => {
    loadBrand();
    try {
      mode = PIPELINE_NAMES[(await getSettings()).pipeline] ?? '';
    } catch {
      mode = '';
    }
  });
</script>

<header class="flex flex-wrap items-center justify-between gap-4 mb-7">
  <h1 class="min-w-0 text-[19px] font-semibold tracking-tight text-gray-900">
    <BrandMark size={32} />
  </h1>

  <div class="flex items-center gap-3">
    <div class="flex items-center gap-2 font-mono text-[12.5px] text-gray-400">
      {#if mode}
        <span class="font-sans text-[12.5px] font-medium text-gray-500">{mode}</span>
      {/if}
      <span>{$formattedTime}</span>
      <span
        role="img"
        aria-label={$session.connected ? 'Connected' : 'Not connected'}
        class="w-2 h-2 rounded-full transition-colors duration-300 {$session.connected
          ? 'bg-brand live-dot'
          : 'bg-gray-300'}"
      ></span>
    </div>

    <a
      href="/desk/"
      class="h-9 px-3.5 flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white
             text-[13.5px] font-medium text-gray-900 hover:bg-gray-100 transition-colors"
    >
      <i class="ph ph-squares-four text-[15px]" aria-hidden="true"></i>
      Open Desk
    </a>
    <a
      href="/logout/"
      class="h-9 px-3 flex items-center gap-1.5 rounded-lg text-[13.5px] font-medium text-danger
             hover:bg-gray-100 transition-colors"
    >
      <i class="ph ph-sign-out text-[15px]" aria-hidden="true"></i>
      Log Out
    </a>
  </div>
</header>

<style>
  .live-dot {
    animation: pulse-dot 2s infinite;
  }
</style>
