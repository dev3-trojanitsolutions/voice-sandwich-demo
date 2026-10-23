<script lang="ts">
  import { session } from '../stores';

  interface Props {
    onStart: () => void;
    onStop: () => void;
  }

  let { onStart, onStop }: Props = $props();

  const statusConfig = {
    ready: { dot: 'bg-success', text: 'Ready' },
    connecting: { dot: 'bg-gray-400', text: 'Connecting...' },
    listening: { dot: 'bg-brand animate-pulse', text: 'Listening...' },
    error: { dot: 'bg-red-500', text: 'Error' },
    disconnected: { dot: 'bg-gray-400', text: 'Disconnected' },
  };

  let config = $derived(statusConfig[$session.status]);
</script>

<div class="bg-white rounded-2xl p-6 mb-5 border border-gray-200">
  <div class="flex gap-3 mb-4">
    <button
      onclick={onStart}
      disabled={$session.connected}
      class="flex-1 h-11 px-5 text-[14px] font-medium bg-accent text-on-accent rounded-[10px]
             flex items-center justify-center gap-2 transition-colors duration-200 cursor-pointer
             hover:bg-accent-hover
             disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <svg width="16" height="16" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
        <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
        <line x1="12" y1="19" x2="12" y2="23"></line>
        <line x1="8" y1="23" x2="16" y2="23"></line>
      </svg>
      Start Session
    </button>
    <button
      onclick={onStop}
      disabled={!$session.connected}
      class="flex-1 h-11 px-5 text-[14px] font-medium bg-white text-gray-900 rounded-[10px] cursor-pointer
             border border-gray-300 transition-all duration-200
             hover:bg-gray-100
             disabled:opacity-50 disabled:cursor-not-allowed"
    >
      End Session
    </button>
  </div>

  <div class="flex items-center gap-2.5 py-2.5 px-3.5 bg-gray-50 border border-gray-200 rounded-lg">
    <span class="w-2.5 h-2.5 rounded-full transition-all duration-300 {config.dot}"></span>
    <span class="text-sm font-medium text-gray-600">{config.text}</span>
  </div>

  {#if $session.connected}
    <div class="mt-3 py-2.5 px-3.5 bg-accent-soft rounded-lg text-[12.5px] text-gray-600 text-center">
      💡 Session is active — just speak naturally. End session when you're done.
    </div>
  {/if}
</div>

