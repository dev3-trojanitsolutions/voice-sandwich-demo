<script lang="ts">
  import { currentTurn } from '../stores';
  import Pipeline from './Pipeline.svelte';
  import LatencyWaterfall from './LatencyWaterfall.svelte';
</script>

<div
  class="pipeline palette-light text-gray-100 rounded-2xl p-6 mb-5">
  <div class="flex items-center justify-between mb-4">
    <span class="text-[15px] font-semibold tracking-[-0.01em] text-white">Pipeline</span>
    <span
      class="font-mono text-[11px] py-1 px-2 rounded
             {$currentTurn.active
               ? 'text-[#ff8a5c] bg-[#ff5b1f]/15'
               : 'text-gray-500 bg-white/5'}"
    >
      {$currentTurn.active ? 'Turn Active' : 'Waiting...'}
    </span>
  </div>

  <div class="transition-opacity duration-300 {$currentTurn.active ? '' : 'opacity-60'}">
    <Pipeline />
    <LatencyWaterfall />
  </div>
</div>


<style>
  .pipeline {
    background-color: #0b0b0c;
    background-image: radial-gradient(120% 80% at 90% 0%, rgb(255 91 31 / 0.16), transparent 60%);
  }
</style>
