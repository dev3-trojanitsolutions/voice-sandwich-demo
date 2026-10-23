<script lang="ts">
  import { onMount } from 'svelte';
  import { getMe, type Permission, type User } from '../api';
  import { brand, loadBrand } from '../brand.svelte';
  import BrandMark from '../components/BrandMark.svelte';
  import AccountSection from './AccountSection.svelte';
  import DashboardSection from './DashboardSection.svelte';
  import UsersSection from './UsersSection.svelte';
  import ConversationsSection from './ConversationsSection.svelte';
  import CustomersSection from './CustomersSection.svelte';
  import OrdersSection from './OrdersSection.svelte';
  import SettingsSection from './SettingsSection.svelte';
  import TrainingSection from './TrainingSection.svelte';
  import FlowSection from './FlowSection.svelte';
  import DeliverySection from './DeliverySection.svelte';

  type Section =
    | 'dashboard'
    | 'conversations'
    | 'customers'
    | 'orders'
    | 'training'
    | 'flow'
    | 'delivery'
    | 'settings'
    | 'users'
    | 'account';

  // A section shows only to users whose role has `permission`, or one of
  // them when it is a list. `icon` is a
  // Phosphor icon class; `about` is the line under the page title.
  const sections: {
    id: Section;
    label: string;
    group: string;
    icon: string;
    about: string;
    permission: Permission | Permission[];
  }[] = [
    {
      id: 'dashboard',
      // Each part of the dashboard shows only what the role can view
      permission: ['conversations.view', 'customers.view'],
      label: 'Dashboard',
      group: 'Workspace',
      icon: 'ph-squares-four',
      about: 'How the agent is doing: conversations, orders and revenue.',
    },
    {
      id: 'conversations',
      permission: 'conversations.view',
      label: 'Conversations',
      group: 'Workspace',
      icon: 'ph-chats-circle',
      about: 'Every conversation with the agent, with the transcript and the order.',
    },
    {
      id: 'customers',
      permission: 'customers.view',
      label: 'Customers',
      group: 'Workspace',
      icon: 'ph-address-book',
      about: 'Every caller, with contact details and their orders.',
    },
    {
      id: 'orders',
      // Orders come with the customers, so they share the permission
      permission: 'customers.view',
      label: 'Orders',
      group: 'Workspace',
      icon: 'ph-receipt',
      about: 'The orders the agent takes in conversations, with the items and the total.',
    },
    {
      id: 'training',
      permission: 'training.view',
      label: 'Training',
      group: 'Agent',
      icon: 'ph-books',
      about: 'The knowledge the agent draws on when it answers.',
    },
    {
      id: 'flow',
      permission: 'flow.view',
      label: 'Flow',
      group: 'Agent',
      icon: 'ph-flow-arrow',
      about: 'The steps the agent follows in every conversation.',
    },
    {
      id: 'delivery',
      permission: 'delivery.view',
      label: 'Delivery',
      group: 'Agent',
      icon: 'ph-map-pin-area',
      about: 'The cities, zones and pincodes you deliver to.',
    },
    {
      id: 'settings',
      permission: 'settings.view',
      label: 'Settings',
      group: 'Admin',
      icon: 'ph-gear-six',
      about: 'Your business details, the voice model and the voices.',
    },
    {
      id: 'users',
      label: 'Users',
      group: 'Admin',
      permission: 'users.manage',
      icon: 'ph-users-three',
      about: 'Who can log in, and what each role can see and change.',
    },
  ];

  const account = {
    label: 'Account',
    about: 'Your login and your password.',
  };

  // null until /api/auth/me answers; a 401 there goes to the login page
  let me = $state<User | null>(null);
  let loadError = $state('');
  let visible = $derived(
    sections.filter((s) =>
      [s.permission].flat().some((p) => me?.permissions.includes(p)),
    ),
  );
  let groups = $derived(
    [...new Set(visible.map((s) => s.group))].map((name) => ({
      name,
      items: visible.filter((s) => s.group === name),
    })),
  );

  // Hash routes: #dashboard, #conversations, #conversations/12, #conversations?q=98765,
  // #customers, #orders, #orders/7, #training, #training/3, #flow, #delivery, #settings, #users,
  // #account. A section the user can't see falls back to the first one they can.
  function readRoute() {
    const [path, search = ''] = location.hash.slice(1).split('?');
    const [name, id] = path.split('/');
    const known = name === 'account' || visible.some((s) => s.id === name);
    const section = known ? (name as Section) : (visible[0]?.id ?? 'account');
    return {
      section,
      id: id && /^\d+$/.test(id) ? Number(id) : null,
      query: new URLSearchParams(search).get('q') ?? '',
    };
  }

  let route = $state(readRoute());
  let page = $derived(sections.find((s) => s.id === route.section) ?? account);

  // The sidebar is a drawer below 900px; the account menu opens from the avatar
  let navOpen = $state(false);
  let menuOpen = $state(false);

  let initials = $derived(
    (me?.name ?? '')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w.charAt(0).toUpperCase())
      .join(''),
  );

  $effect(() => {
    document.title = `${page.label} · ${brand.current.name} Desk`;
  });

  function closeAll() {
    navOpen = false;
    menuOpen = false;
  }

  onMount(() => {
    loadBrand();
    getMe()
      .then((user) => {
        me = user;
        route = readRoute();
      })
      .catch((e) => (loadError = `Can't load the desk. ${(e as Error).message}`));
    const onHashChange = () => {
      const next = readRoute();
      if (next.section !== route.section) window.scrollTo(0, 0);
      route = next;
      closeAll();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeAll();
    };
    const onClick = (e: MouseEvent) => {
      if (menuOpen && !(e.target as Element).closest('[data-account-menu]')) menuOpen = false;
    };
    window.addEventListener('hashchange', onHashChange);
    window.addEventListener('keydown', onKey);
    window.addEventListener('click', onClick);
    return () => {
      window.removeEventListener('hashchange', onHashChange);
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('click', onClick);
    };
  });
</script>

{#if !me}
  <p class="px-4 py-10 text-center text-[13.5px] {loadError ? 'text-danger' : 'text-gray-400'}" role="status">
    {loadError || 'Loading…'}
  </p>
{:else}
<div class="desk min-h-screen flex">
  <aside
    aria-label="Sidebar"
    class="sidebar {navOpen ? 'open' : ''} flex flex-col gap-5 w-[236px] shrink-0 h-screen
           px-2.5 pl-3 py-3.5 overflow-y-auto bg-gray-50"
  >
    <div class="flex items-center gap-2.5 px-1.5 py-1">
      <span class="min-w-0 flex-1 text-[14.5px] font-semibold tracking-tight">
        <BrandMark suffix="Desk" size={28} />
      </span>
      <button
        type="button"
        aria-label="Close menu"
        onclick={() => (navOpen = false)}
        class="drawer-only w-8 h-8 grid place-items-center rounded-lg text-gray-500
               hover:bg-gray-100 cursor-pointer"
      >
        <i class="ph ph-x text-[17px]" aria-hidden="true"></i>
      </button>
    </div>

    <nav aria-label="Desk" class="flex flex-col gap-[18px] flex-1">
      {#each groups as g (g.name)}
        <div class="flex flex-col gap-px">
          <p class="px-2.5 pb-1.5 text-[11.5px] font-medium text-gray-400">{g.name}</p>
          {#each g.items as s (s.id)}
            {@const current = route.section === s.id}
            <a
              href="#{s.id}"
              aria-current={current ? 'page' : undefined}
              class="nav-item flex items-center gap-2.5 h-[34px] px-2.5 rounded-lg text-[13.5px]
                     text-gray-900 transition-colors {current ? 'current font-medium' : ''}"
            >
              <i
                class="ph {s.icon} text-[17px] {current ? 'text-brand' : 'text-gray-500'}"
                aria-hidden="true"
              ></i>
              <span class="flex-1">{s.label}</span>
            </a>
          {/each}
        </div>
      {/each}
    </nav>

    <a
      href="/"
      class="flex flex-col gap-1 p-3 rounded-[10px] bg-white border border-gray-200
             hover:border-gray-300 transition-colors"
    >
      <span class="flex items-center gap-2 text-[13px] font-medium">
        <span class="live-dot w-[7px] h-[7px] rounded-full bg-brand" aria-hidden="true"></span>
        Order Page
      </span>
      <span class="text-[12px] text-gray-400">Talk to the agent as a customer</span>
    </a>
  </aside>

  {#if navOpen}
    <button
      type="button"
      aria-label="Close menu"
      onclick={() => (navOpen = false)}
      class="drawer-only fixed inset-0 z-40 bg-black/30 backdrop-blur-[2px]"
    ></button>
  {/if}

  <div class="sheet-wrap flex-1 min-w-0 flex">
    <div class="sheet flex-1 min-w-0 flex flex-col bg-white">
      <header
        class="sheet-header sticky top-0 z-30 flex items-center gap-3 h-14 px-4 md:px-8
               bg-white/85 backdrop-blur-xl border-b border-gray-200"
      >
        <button
          type="button"
          aria-label="Open menu"
          onclick={() => (navOpen = true)}
          class="drawer-only w-[34px] h-[34px] grid place-items-center rounded-lg border
                 border-gray-300 bg-white text-gray-900 cursor-pointer"
        >
          <i class="ph ph-list text-[18px]" aria-hidden="true"></i>
        </button>
        <p class="flex items-center gap-2 min-w-0 text-[13.5px]">
          <span class="text-gray-400 truncate">{brand.current.name}</span>
          <span class="text-gray-300" aria-hidden="true">/</span>
          <span class="font-medium whitespace-nowrap">{page.label}</span>
        </p>
        <span class="flex-1"></span>

        <div class="relative" data-account-menu>
          <button
            type="button"
            aria-label="Account menu"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onclick={() => (menuOpen = !menuOpen)}
            class="w-8 h-8 rounded-full bg-accent text-on-accent text-[12px] font-semibold
                   tracking-wide cursor-pointer"
          >
            {initials || '?'}
          </button>
          {#if menuOpen}
            <div
              role="menu"
              class="absolute right-0 top-[42px] z-40 w-60 p-1.5 rounded-xl bg-white border
                     border-gray-200 shadow-[0_16px_48px_rgba(0,0,0,0.12)]"
            >
              <div class="px-2.5 pt-2.5 pb-3 mb-1 border-b border-gray-200">
                <p class="text-[13.5px] font-semibold truncate">{me.name}</p>
                <p class="text-[12px] text-gray-400 truncate">{me.username} · {me.role_name}</p>
              </div>
              <a role="menuitem" href="#account" class="menu-item">
                <i class="ph ph-user-circle text-[16px] text-gray-500" aria-hidden="true"></i>
                Account
              </a>
              <a role="menuitem" href="/" class="menu-item">
                <i class="ph ph-microphone text-[16px] text-gray-500" aria-hidden="true"></i>
                Order Page
              </a>
              <a role="menuitem" href="/logout/" class="menu-item text-danger">
                <i class="ph ph-sign-out text-[16px]" aria-hidden="true"></i>
                Log Out
              </a>
            </div>
          {/if}
        </div>
      </header>

      <main class="flex-1 w-full max-w-[1280px] px-4 md:px-8 pt-7 pb-16">
        <div class="flex flex-col gap-1 mb-7">
          <h1 class="text-[24px] leading-tight font-semibold tracking-[-0.025em]">{page.label}</h1>
          <p class="text-[14px] text-gray-500">{page.about}</p>
        </div>

        {#if route.section === 'dashboard'}
          <DashboardSection {me} />
        {:else if route.section === 'conversations'}
          <ConversationsSection selectedId={route.id} initialQuery={route.query} />
        {:else if route.section === 'customers'}
          <CustomersSection />
        {:else if route.section === 'orders'}
          <OrdersSection selectedId={route.id} />
        {:else if route.section === 'training'}
          <TrainingSection selectedId={route.id} />
        {:else if route.section === 'flow'}
          <FlowSection />
        {:else if route.section === 'delivery'}
          <DeliverySection />
        {:else if route.section === 'settings'}
          <SettingsSection />
        {:else if route.section === 'users'}
          <UsersSection {me} />
        {:else}
          <AccountSection {me} />
        {/if}
      </main>
    </div>
  </div>
</div>
{/if}

<style>
  .nav-item:hover {
    background: var(--g100);
  }

  .nav-item.current {
    background: var(--surface);
    box-shadow:
      0 1px 2px rgb(0 0 0 / 0.06),
      0 0 0 1px var(--g200);
  }

  .live-dot {
    animation: pulse-dot 2s infinite;
  }

  .menu-item {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 34px;
    padding: 0 10px;
    border-radius: 8px;
    font-size: 13.5px;
  }

  .menu-item:hover {
    background: var(--g100);
  }

  /* Wide: the sidebar sits beside a white sheet with a rounded edge */
  .sidebar {
    position: sticky;
    top: 0;
  }

  .sheet-wrap {
    padding: 10px 10px 10px 0;
  }

  .sheet {
    border: 1px solid var(--g200);
    border-radius: 14px;
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.03);
  }

  .sheet-header {
    border-radius: 14px 14px 0 0;
  }

  .drawer-only {
    display: none;
  }

  /* Narrow: the sidebar is a drawer and the sheet fills the screen */
  @media (max-width: 899px) {
    .sidebar {
      position: fixed;
      left: 0;
      z-index: 45;
      transform: translateX(-100%);
      transition: transform 0.24s cubic-bezier(0.2, 0.8, 0.2, 1);
    }

    .sidebar.open {
      transform: none;
      box-shadow: 0 24px 64px rgb(0 0 0 / 0.2);
    }

    .sheet-wrap {
      padding: 0;
    }

    .sheet,
    .sheet-header {
      border: none;
      border-radius: 0;
    }

    .sheet-header {
      border-bottom: 1px solid var(--g200);
    }

    .drawer-only {
      display: grid;
    }
  }
</style>
