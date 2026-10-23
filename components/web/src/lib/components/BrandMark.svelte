<script lang="ts">
  import { logoUrl } from '../api';
  import { brand } from '../brand.svelte';

  // `suffix` follows the name, e.g. "Desk". `size` is the logo height in px.
  let { suffix = '', size = 28 }: { suffix?: string; size?: number } = $props();

  let logo = $derived(logoUrl(brand.current));
</script>

<span class="inline-flex items-center gap-2.5 min-w-0">
  {#if logo}
    <img
      src={logo}
      alt=""
      style:height="{size}px"
      style:max-width="{size * 3}px"
      class="w-auto shrink-0 object-contain rounded-md"
    />
  {:else if brand.current.icon}
    <span aria-hidden="true" style:font-size="{size * 0.85}px" class="leading-none">
      {brand.current.icon}
    </span>
  {/if}
  <span class="truncate">{brand.current.name}{suffix ? ` ${suffix}` : ''}</span>
</span>
