<script lang="ts">
  import { onMount } from 'svelte';
  import {
    addRole,
    addUser,
    deleteRole,
    deleteUser,
    formatDate,
    getRoles,
    getUsers,
    updateRole,
    updateUser,
    type Permission,
    type Role,
    type Roles,
    type User,
    type UserInput,
  } from '../api';

  let { me }: { me: User } = $props();

  let users = $state<User[]>([]);
  let roles = $state<Roles>({ roles: [], permissions: [] });
  let loaded = $state(false);
  let listError = $state('');

  // The user or role being edited: 'new', its id, or null
  let editingUser = $state<'new' | number | null>(null);
  let userForm = $state<UserInput>(blankUser());
  let userError = $state('');

  let editingRole = $state<'new' | number | null>(null);
  let roleName = $state('');
  let rolePermissions = $state<Permission[]>([]);
  let roleError = $state('');

  let saving = $state(false);

  function blankUser(): UserInput {
    return { username: '', name: '', role_id: 0, active: true, password: '' };
  }

  async function load() {
    try {
      [users, roles] = await Promise.all([getUsers(), getRoles()]);
      listError = '';
    } catch (e) {
      listError = `Can't load users. ${(e as Error).message}`;
    } finally {
      loaded = true;
    }
  }

  function editUser(target: User | 'new') {
    userError = '';
    if (target === 'new') {
      const staff = roles.roles.find((r) => r.name === 'Staff') ?? roles.roles[0];
      userForm = { ...blankUser(), role_id: staff?.id ?? 0 };
      editingUser = 'new';
    } else {
      const { username, name, role_id, active } = target;
      userForm = { username, name, role_id, active, password: '' };
      editingUser = target.id;
    }
  }

  async function saveUser(event: SubmitEvent) {
    event.preventDefault();
    userError = '';
    if (!userForm.name.trim() || !userForm.username.trim()) {
      userError = 'Enter a name and a username.';
      return;
    }
    if (editingUser === 'new' && !userForm.password) {
      userError = 'Enter a password for the new user.';
      return;
    }
    saving = true;
    try {
      if (editingUser === 'new') await addUser(userForm);
      else await updateUser(editingUser as number, userForm);
      editingUser = null;
      await load();
    } catch (e) {
      userError = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  async function removeUser(user: User) {
    if (!confirm(`Delete ${user.name}? They can't log in again.`)) return;
    saving = true;
    try {
      await deleteUser(user.id);
      editingUser = null;
      await load();
    } catch (e) {
      userError = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  function editRole(target: Role | 'new') {
    roleError = '';
    roleName = target === 'new' ? '' : target.name;
    rolePermissions = target === 'new' ? [] : [...target.permissions];
    editingRole = target === 'new' ? 'new' : target.id;
  }

  function togglePermission(id: Permission, on: boolean) {
    rolePermissions = on ? [...rolePermissions, id] : rolePermissions.filter((p) => p !== id);
    // "edit" is no use without "view" of the same section
    const [section, action] = id.split('.');
    const view = `${section}.view` as Permission;
    if (on && action === 'edit' && !rolePermissions.includes(view)) {
      rolePermissions = [...rolePermissions, view];
    }
    if (!on && action === 'view') {
      rolePermissions = rolePermissions.filter((p) => p !== `${section}.edit`);
    }
  }

  async function saveRole(event: SubmitEvent) {
    event.preventDefault();
    roleError = '';
    if (!roleName.trim()) {
      roleError = 'Enter a name for the role.';
      return;
    }
    saving = true;
    try {
      roles =
        editingRole === 'new'
          ? await addRole(roleName, rolePermissions)
          : await updateRole(editingRole as number, roleName, rolePermissions);
      editingRole = null;
      users = await getUsers();
    } catch (e) {
      roleError = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  async function removeRole(role: Role) {
    if (!confirm(`Delete the role ${role.name}?`)) return;
    saving = true;
    try {
      roles = await deleteRole(role.id);
      editingRole = null;
    } catch (e) {
      roleError = (e as Error).message;
    } finally {
      saving = false;
    }
  }

  const isAdminRole = (role: Role) => role.builtin && role.name === 'Admin';

  onMount(load);
</script>

{#snippet chevron(open: boolean)}
  <svg
    class="w-3 h-3 shrink-0 text-gray-400 transition-transform {open ? 'rotate-90' : ''}"
    viewBox="0 0 12 12"
    aria-hidden="true"
  >
    <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
  </svg>
{/snippet}

{#snippet userEditor(user: User | null)}
  <form
    onsubmit={saveUser}
    novalidate
    class="border-t border-gray-200 bg-gray-100/50"
    aria-label={user ? `Edit ${user.name}` : 'New user'}
  >
    <label class="field">
      <span class="field-label">Name</span>
      <input bind:value={userForm.name} autocomplete="off" placeholder="Asha Rao" class="field-input" />
    </label>
    <label class="field border-t border-gray-200">
      <span class="field-label">Username</span>
      <input
        bind:value={userForm.username}
        autocomplete="off"
        autocapitalize="none"
        spellcheck="false"
        placeholder="asha"
        class="field-input"
      />
    </label>
    <label class="field border-t border-gray-200">
      <span class="field-label">Role</span>
      <select bind:value={userForm.role_id} class="field-input cursor-pointer">
        {#each roles.roles as role (role.id)}
          <option value={role.id}>{role.name}</option>
        {/each}
      </select>
    </label>
    <label class="field border-t border-gray-200">
      <span class="field-label">Password</span>
      <input
        bind:value={userForm.password}
        type="password"
        autocomplete="new-password"
        placeholder={user ? 'Leave empty to keep' : 'At least 4 characters'}
        class="field-input"
      />
    </label>
    {#if user?.id !== me.id}
      <label class="field border-t border-gray-200 cursor-pointer">
        <span class="flex-1 text-[14.5px]">Can log in</span>
        <input type="checkbox" bind:checked={userForm.active} class="w-5 h-5 accent-[var(--brand)]" />
      </label>
    {/if}
    <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
      <p class="flex-1 min-w-48 text-[12.5px]" aria-live="polite">
        {#if userError}
          <span class="text-danger">{userError}</span>
        {:else if user && user.id !== me.id}
          <span class="text-gray-400">A new password logs the user out on every device.</span>
        {/if}
      </p>
      {#if user && user.id !== me.id}
        <button
          type="button"
          onclick={() => removeUser(user)}
          disabled={saving}
          class="min-h-9 px-4 rounded-xl text-[13.5px] font-medium text-danger hover:bg-gray-100
                 transition-colors cursor-pointer disabled:opacity-60"
        >
          Delete
        </button>
      {/if}
      <button
        type="button"
        onclick={() => (editingUser = null)}
        class="min-h-9 px-4 rounded-xl text-[13.5px] font-medium text-gray-600 hover:bg-gray-100
               transition-colors cursor-pointer"
      >
        Cancel
      </button>
      <button
        type="submit"
        disabled={saving}
        class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
               hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-60"
      >
        {saving ? 'Saving…' : user ? 'Save' : 'Add User'}
      </button>
    </div>
  </form>
{/snippet}

{#snippet roleEditor(role: Role | null)}
  {@const locked = role !== null && isAdminRole(role)}
  <form
    onsubmit={saveRole}
    novalidate
    class="border-t border-gray-200 bg-gray-100/50"
    aria-label={role ? `Edit ${role.name}` : 'New role'}
  >
    {#if !locked}
      <label class="field">
        <span class="field-label">Name</span>
        <input bind:value={roleName} autocomplete="off" placeholder="Cashier" class="field-input" />
      </label>
    {/if}
    <fieldset class="px-5 py-3 {locked ? '' : 'border-t border-gray-200'}">
      <legend class="sr-only">Permissions</legend>
      {#if locked}
        <p class="pb-2 text-[12.5px] text-gray-500">
          Admin always has every permission. Make a new role for a smaller set.
        </p>
      {/if}
      <ul class="flex flex-col">
        {#each roles.permissions as permission (permission.id)}
          <li>
            <label class="flex items-center gap-3 min-h-9 {locked ? '' : 'cursor-pointer'}">
              <input
                type="checkbox"
                checked={locked || rolePermissions.includes(permission.id)}
                disabled={locked}
                onchange={(e) => togglePermission(permission.id, e.currentTarget.checked)}
                class="w-5 h-5 shrink-0 accent-[var(--brand)]"
              />
              <span class="flex-1 text-[13.5px]">{permission.label}</span>
              <code class="text-[12px] text-gray-400">{permission.id}</code>
            </label>
          </li>
        {/each}
      </ul>
    </fieldset>
    {#if !locked}
      <div class="flex flex-wrap items-center gap-3 px-5 py-4 border-t border-gray-200">
        <p class="flex-1 min-w-48 text-[12.5px] text-danger" aria-live="polite">{roleError}</p>
        {#if role}
          <button
            type="button"
            onclick={() => removeRole(role)}
            disabled={saving}
            class="min-h-9 px-4 rounded-xl text-[13.5px] font-medium text-danger hover:bg-gray-100
                   transition-colors cursor-pointer disabled:opacity-60"
          >
            Delete
          </button>
        {/if}
        <button
          type="button"
          onclick={() => (editingRole = null)}
          class="min-h-9 px-4 rounded-xl text-[13.5px] font-medium text-gray-600 hover:bg-gray-100
                 transition-colors cursor-pointer"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          class="min-h-9 px-5 rounded-xl bg-accent text-on-accent text-[13.5px] font-semibold
                 hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-60"
        >
          {saving ? 'Saving…' : role ? 'Save' : 'Add Role'}
        </button>
      </div>
    {/if}
  </form>
{/snippet}

<div class="max-w-2xl">
  {#if listError}
    <p class="mb-6 text-[13.5px] text-danger" role="alert">{listError}</p>
  {/if}

  <!-- Users -->
  <section aria-labelledby="users-title" class="mb-8">
    <div class="flex items-baseline justify-between">
      <h2 id="users-title" class="group-title">Users</h2>
      {#if editingUser !== 'new' && loaded}
        <button
          onclick={() => editUser('new')}
          class="mb-2 text-[13.5px] font-medium text-link cursor-pointer"
        >
          Add User
        </button>
      {/if}
    </div>
    <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
      {#if !loaded}
        <p class="px-5 py-6 text-[13.5px] text-gray-400">Loading…</p>
      {:else}
        {#if editingUser === 'new'}
          <div class="-mt-px">{@render userEditor(null)}</div>
        {/if}
        <ul>
          {#each users as user (user.id)}
            {@const open = editingUser === user.id}
            <li class="border-t border-gray-200 first:border-t-0">
              <button
                onclick={() => (open ? (editingUser = null) : editUser(user))}
                aria-expanded={open}
                class="w-full flex items-center gap-4 px-5 py-3.5 min-h-16 text-left
                       hover:bg-gray-100 transition-colors cursor-pointer"
              >
                <span
                  class="w-10 h-10 shrink-0 rounded-full bg-accent-soft text-link
                         flex items-center justify-center text-[14.5px] font-semibold"
                  aria-hidden="true"
                >
                  {user.name.charAt(0).toUpperCase()}
                </span>
                <span class="flex-1 min-w-0">
                  <span class="block text-[14.5px] font-medium truncate">
                    {user.name}
                    {#if user.id === me.id}<span class="text-[12.5px] text-gray-400"> (you)</span>{/if}
                  </span>
                  <span class="block text-[13.5px] text-gray-500 truncate">
                    {user.username} · {user.role_name}
                  </span>
                </span>
                <span class="text-right shrink-0 text-[12.5px]">
                  {#if !user.active}
                    <span class="block font-semibold text-danger">Can't log in</span>
                  {/if}
                  <span class="block text-gray-400">
                    {user.last_login_at ? `Last login ${formatDate(user.last_login_at)}` : 'Never logged in'}
                  </span>
                </span>
                {@render chevron(open)}
              </button>
              {#if open}
                {@render userEditor(user)}
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </section>

  <!-- Roles -->
  <section aria-labelledby="roles-title">
    <div class="flex items-baseline justify-between">
      <h2 id="roles-title" class="group-title">Roles and Permissions</h2>
      {#if editingRole !== 'new' && loaded}
        <button
          onclick={() => editRole('new')}
          class="mb-2 text-[13.5px] font-medium text-link cursor-pointer"
        >
          Add Role
        </button>
      {/if}
    </div>
    <div class="bg-white rounded-2xl border border-gray-200 overflow-hidden">
      {#if editingRole === 'new'}
        <div class="-mt-px">{@render roleEditor(null)}</div>
      {/if}
      <ul>
        {#each roles.roles as role (role.id)}
          {@const open = editingRole === role.id}
          <li class="border-t border-gray-200 first:border-t-0">
            <button
              onclick={() => (open ? (editingRole = null) : editRole(role))}
              aria-expanded={open}
              class="w-full flex items-center gap-4 px-5 py-3.5 min-h-12 text-left
                     hover:bg-gray-100 transition-colors cursor-pointer"
            >
              <span class="flex-1 min-w-0">
                <span class="block text-[14.5px] font-medium truncate">{role.name}</span>
                <span class="block text-[12.5px] text-gray-500">
                  {isAdminRole(role)
                    ? 'Every permission'
                    : `${role.permissions.length} of ${roles.permissions.length} permissions`}
                </span>
              </span>
              <span class="shrink-0 text-[13.5px] text-gray-600">
                {role.user_count === 1 ? '1 user' : `${role.user_count} users`}
              </span>
              {@render chevron(open)}
            </button>
            {#if open}
              {@render roleEditor(role)}
            {/if}
          </li>
        {/each}
      </ul>
    </div>
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
