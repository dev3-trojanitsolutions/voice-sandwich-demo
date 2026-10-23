<script lang="ts">
  import { Header, Controls, PipelineCard, ActivityFeed, Console } from './lib/components';
  import { createVoiceSession } from './lib/websocket';

  // The admin page moved to the desk; keep old bookmarks working
  if (location.hash === '#/admin') location.replace('/desk/');

  const voiceSession = createVoiceSession();
</script>

<div class="max-w-3xl mx-auto">
  <Header />
  <main>
    <Controls onStart={() => voiceSession.start()} onStop={() => voiceSession.stop()} />
    <PipelineCard />
    <ActivityFeed />
    <Console />
  </main>
</div>
