// Desk API on the Python server (components/python/src/main.py)

export type Pipeline = "realtime" | "ollama" | "sandwich";

export interface Settings {
  pipeline: Pipeline;
  local_model: string;
  gemini_ready: boolean;
}

export interface OrderRecord {
  id: number;
  address: string;
  // price is the unit price in rupees; orders saved before prices have none
  items: { item: string; quantity: number; price?: number }[];
  payment_method: string;
  status: "confirmed" | "cancelled";
  channel: Pipeline | "";
  created_at: number;
  details: Record<string, string>;
  // Rupees; 0 for orders saved before prices
  total: number;
}

export interface Customer {
  phone: string;
  name: string;
  created_at: number;
  orders: OrderRecord[];
  last_active: number;
}

export interface ConversationSummary {
  id: number;
  channel: Pipeline;
  name: string;
  phone: string;
  outcome: "confirmed" | "cancelled" | "";
  started_at: number;
  ended_at: number | null;
  message_count: number;
  preview: string;
}

export interface Message {
  id: number;
  role: "customer" | "agent" | "tool";
  text: string;
  tool_name: string;
  tool_args: Record<string, unknown> | null;
  created_at: number;
}

export interface Conversation extends Omit<ConversationSummary, "message_count" | "preview"> {
  messages: Message[];
}

export type ModuleKind = "menu" | "notes" | "qa";

export interface Section {
  id: number;
  module_id: number;
  title: string;
  body: string;
  position: number;
  created_at: number;
  updated_at: number;
}

export interface KnowledgeModule {
  id: number;
  name: string;
  kind: ModuleKind;
  intro: string;
  position: number;
  created_at: number;
  updated_at: number;
  sections: Section[];
}

export interface KnowledgeMatch {
  id: string;
  source: string;
  module_id: number;
  text: string;
  distance: number;
}

export interface FlowStep {
  key: string;
  kind: "builtin" | "custom";
  label: string;
  ask: string;
  notes: string;
  required: boolean;
  choices: string[];
  tools?: string[];
}

export interface Flow {
  steps: FlowStep[];
  is_default: boolean;
  greeting: string;
  prompt: string;
}

export const PIPELINE_NAMES: Record<string, string> = {
  realtime: "Gemini",
  ollama: "Local",
  sandwich: "Claude",
};

/** The login page, coming back to the current page after the login. */
export function loginUrl(): string {
  const next = location.pathname + location.hash;
  return `/login/?next=${encodeURIComponent(next)}`;
}

const AUTH_PAGES = ["/login/", "/logout/"];

// A 401 means the session ended (logout, expiry or a deactivated user). The
// login and logout pages expect it, so they stay where they are.
function checkSession(response: Response, path: string) {
  if (response.status !== 401 || path === "/api/auth/login") return;
  if (!AUTH_PAGES.some((page) => location.pathname.startsWith(page))) {
    location.assign(loginUrl());
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json" },
  });
  checkSession(response, path);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail ?? `The server returned ${response.status}.`);
  }
  return body as T;
}

export const getSettings = () => request<Settings>("/api/settings");

export const setPipeline = (pipeline: Pipeline) =>
  request<Settings>("/api/settings", {
    method: "PUT",
    body: JSON.stringify({ pipeline }),
  });

export interface GeminiKeyStatus {
  set: boolean;
  /** "desk" when saved in Settings, "env" when it comes from .env */
  source: "desk" | "env" | "";
  /** The key's last four characters; the server never sends the whole key */
  hint: string;
}

export const getGeminiKey = () => request<GeminiKeyStatus>("/api/settings/gemini-key");

export const saveGeminiKey = (key: string) =>
  request<GeminiKeyStatus>("/api/settings/gemini-key", {
    method: "PUT",
    body: JSON.stringify({ key }),
  });

export const removeGeminiKey = () =>
  request<GeminiKeyStatus>("/api/settings/gemini-key", { method: "DELETE" });

export const getCustomers = () => request<Customer[]>("/api/customers");

export const addCustomer = (name: string, phone: string) =>
  request<{ name: string; phone: string }>("/api/customers", {
    method: "POST",
    body: JSON.stringify({ name, phone }),
  });

export const getConversations = () => request<ConversationSummary[]>("/api/conversations");

export const getConversation = (id: number) =>
  request<Conversation>(`/api/conversations/${id}`);

export const getModules = () => request<KnowledgeModule[]>("/api/modules");

export const addModule = (name: string, kind: ModuleKind, intro: string) =>
  request<KnowledgeModule>("/api/modules", {
    method: "POST",
    body: JSON.stringify({ name, kind, intro }),
  });

export const updateModule = (id: number, name: string, kind: ModuleKind, intro: string) =>
  request<KnowledgeModule>(`/api/modules/${id}`, {
    method: "PUT",
    body: JSON.stringify({ name, kind, intro }),
  });

export const deleteModule = (id: number) =>
  request<null>(`/api/modules/${id}`, { method: "DELETE" });

export const reorderModules = (ids: number[]) =>
  request<KnowledgeModule[]>("/api/modules/reorder", {
    method: "POST",
    body: JSON.stringify({ ids }),
  });

export const addSection = (moduleId: number, title: string, body: string) =>
  request<KnowledgeModule>(`/api/modules/${moduleId}/sections`, {
    method: "POST",
    body: JSON.stringify({ title, body }),
  });

export const updateSection = (id: number, title: string, body: string) =>
  request<KnowledgeModule>(`/api/sections/${id}`, {
    method: "PUT",
    body: JSON.stringify({ title, body }),
  });

export const deleteSection = (id: number) =>
  request<KnowledgeModule>(`/api/sections/${id}`, { method: "DELETE" });

export const reorderSections = (moduleId: number, ids: number[]) =>
  request<KnowledgeModule>(`/api/modules/${moduleId}/sections/reorder`, {
    method: "POST",
    body: JSON.stringify({ ids }),
  });

export const testKnowledge = (question: string) =>
  request<KnowledgeMatch[]>("/api/knowledge/test", {
    method: "POST",
    body: JSON.stringify({ question }),
  });

export const getFlow = () => request<Flow>("/api/flow");

export const saveFlow = (steps: FlowStep[]) =>
  request<Flow>("/api/flow", {
    method: "PUT",
    body: JSON.stringify({ steps }),
  });

export const resetFlow = () => request<Flow>("/api/flow/reset", { method: "POST" });

// Delivery areas. Every edit returns all cities again.

export interface DeliveryPincode {
  pincode: string;
  // Locality names, e.g. "Koramangala"
  areas: string[];
  active: boolean;
}

export interface DeliveryZone {
  id: number;
  name: string;
  active: boolean;
  pincodes: DeliveryPincode[];
}

export interface DeliveryCity {
  id: number;
  name: string;
  // Other names the customer may use, e.g. "bangalore"
  aliases: string[];
  active: boolean;
  zones: DeliveryZone[];
}

const deliveryEdit = (path: string, method: string, body?: unknown) =>
  request<DeliveryCity[]>(`/api/delivery${path}`, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const getDelivery = () => request<DeliveryCity[]>("/api/delivery");

export const addCity = (name: string, aliases: string[]) =>
  deliveryEdit("/cities", "POST", { name, aliases });

export const updateCity = (id: number, name: string, aliases: string[], active: boolean) =>
  deliveryEdit(`/cities/${id}`, "PUT", { name, aliases, active });

export const deleteCity = (id: number) => deliveryEdit(`/cities/${id}`, "DELETE");

export const addZone = (cityId: number, name: string) =>
  deliveryEdit(`/cities/${cityId}/zones`, "POST", { name });

export const updateZone = (id: number, name: string, active: boolean) =>
  deliveryEdit(`/zones/${id}`, "PUT", { name, active });

export const deleteZone = (id: number) => deliveryEdit(`/zones/${id}`, "DELETE");

export const addPincode = (zoneId: number, pincode: string, areas: string[]) =>
  deliveryEdit(`/zones/${zoneId}/pincodes`, "POST", { pincode, areas });

// `old` is the pincode as saved; `pin.pincode` may change it
export const updatePincode = (old: string, pin: DeliveryPincode, zoneId: number) =>
  deliveryEdit(`/pincodes/${old}`, "PUT", { ...pin, zone_id: zoneId });

export const deletePincode = (pincode: string) => deliveryEdit(`/pincodes/${pincode}`, "DELETE");

export const resetDelivery = () => deliveryEdit("/reset", "POST");

export interface VoiceVersion {
  id: number;
  name: string;
  accent: string;
  accent_label: string;
  created_at: number;
}

export interface Voice extends VoiceVersion {
  versions: VoiceVersion[];
}

export interface VoiceLibrary {
  voices: Voice[];
  /** null when Cartesia speaks */
  active_id: number | null;
  service: { running: boolean; ready: boolean; error: string };
  script: string;
  accents: Record<string, string>;
  min_seconds: number;
  max_seconds: number;
}

export const getVoices = () => request<VoiceLibrary>("/api/voices");

export async function addVoice(name: string, wav: Blob): Promise<Voice> {
  const response = await fetch(`/api/voices?name=${encodeURIComponent(name)}`, {
    method: "POST",
    headers: { "Content-Type": "audio/wav" },
    body: wav,
  });
  checkSession(response, "/api/voices");
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail ?? `The server returned ${response.status}.`);
  }
  return body as Voice;
}

export async function deleteVoice(id: number): Promise<void> {
  const response = await fetch(`/api/voices/${id}`, { method: "DELETE" });
  checkSession(response, "/api/voices");
  if (!response.ok) throw new Error(`The server returned ${response.status}.`);
}

export const addAccent = (id: number, accent: string) =>
  request<VoiceVersion>(`/api/voices/${id}/accents`, {
    method: "POST",
    body: JSON.stringify({ accent }),
  });

export const chooseVoice = (id: number | null) =>
  request<VoiceLibrary>("/api/voices/active", {
    method: "PUT",
    body: JSON.stringify({ id }),
  });

export const voiceAudioUrl = (id: number) => `/api/voices/${id}/audio`;

/** The voice as callers hear it, as a WAV file. */
export async function previewVoice(id: number): Promise<Blob> {
  const response = await fetch(`/api/voices/${id}/preview`, { method: "POST" });
  checkSession(response, "/api/voices");
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `The server returned ${response.status}.`);
  }
  return response.blob();
}

// Desk users, roles and permissions (components/python/src/auth.py)

export type Permission =
  | "conversations.view"
  | "customers.view"
  | "customers.edit"
  | "training.view"
  | "training.edit"
  | "flow.view"
  | "flow.edit"
  | "delivery.view"
  | "delivery.edit"
  | "settings.view"
  | "settings.edit"
  | "users.manage";

export interface User {
  id: number;
  username: string;
  name: string;
  role_id: number;
  role_name: string;
  permissions: Permission[];
  active: boolean;
  created_at: number;
  last_login_at: number | null;
}

export interface Role {
  id: number;
  name: string;
  permissions: Permission[];
  /** Admin, Manager and Staff. Only Admin can't be changed. */
  builtin: boolean;
  user_count: number;
}

export interface Roles {
  roles: Role[];
  permissions: { id: Permission; label: string }[];
}

export interface UserInput {
  username: string;
  name: string;
  role_id: number;
  active: boolean;
  /** Required for a new user. On an edit, empty keeps the password. */
  password: string;
}

export const login = (username: string, password: string) =>
  request<User>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });

export const logout = () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" });

export const getMe = () => request<User>("/api/auth/me");

export const changePassword = (current: string, next: string) =>
  request<{ ok: boolean }>("/api/auth/password", {
    method: "PUT",
    body: JSON.stringify({ current, new: next }),
  });

export const getUsers = () => request<User[]>("/api/users");

export const addUser = (user: UserInput) =>
  request<User>("/api/users", { method: "POST", body: JSON.stringify(user) });

export const updateUser = (id: number, user: UserInput) =>
  request<User>(`/api/users/${id}`, { method: "PUT", body: JSON.stringify(user) });

export const deleteUser = (id: number) =>
  request<null>(`/api/users/${id}`, { method: "DELETE" });

export const getRoles = () => request<Roles>("/api/roles");

export const addRole = (name: string, permissions: Permission[]) =>
  request<Roles>("/api/roles", { method: "POST", body: JSON.stringify({ name, permissions }) });

export const updateRole = (id: number, name: string, permissions: Permission[]) =>
  request<Roles>(`/api/roles/${id}`, {
    method: "PUT",
    body: JSON.stringify({ name, permissions }),
  });

export const deleteRole = (id: number) => request<Roles>(`/api/roles/${id}`, { method: "DELETE" });

// Business details (components/python/src/brand.py)

export interface BrandDetails {
  name: string;
  description: string;
  city: string;
  phone: string;
  email: string;
  address: string;
  /** Emoji shown when there is no logo */
  icon: string;
}

export interface Brand extends BrandDetails {
  /** 0 when there is no logo; changes with each upload */
  logo_version: number;
}

export const getBrand = () => request<Brand>("/api/brand");

export const saveBrand = (details: BrandDetails) =>
  request<Brand>("/api/brand", { method: "PUT", body: JSON.stringify(details) });

export async function uploadLogo(file: File): Promise<Brand> {
  const response = await fetch("/api/brand/logo", {
    method: "POST",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  checkSession(response, "/api/brand/logo");
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail ?? `The server returned ${response.status}.`);
  }
  return body as Brand;
}

export const removeLogo = () => request<Brand>("/api/brand/logo", { method: "DELETE" });

/** The logo URL, or null. The version makes the browser load a new logo. */
export const logoUrl = (brand: Brand) =>
  brand.logo_version ? `/api/brand/logo?v=${brand.logo_version}` : null;

export function formatPhone(phone: string): string {
  return `+91 ${phone.slice(0, 5)} ${phone.slice(5)}`;
}

export function formatDate(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}
