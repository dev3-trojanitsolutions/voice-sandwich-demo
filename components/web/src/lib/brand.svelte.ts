// The business name, icon and logo, shared by every page. Settings → Business
// sets `brand.current` after a save, so the header and sidebar update at once.

import { getBrand, logoUrl, type Brand } from "./api";

// Until the server answers, and if it can't
const FALLBACK: Brand = {
  name: "Ustad Hotel",
  description: "",
  city: "",
  phone: "",
  email: "",
  address: "",
  icon: "🍛",
  logo_version: 0,
};

export const brand = $state<{ current: Brand }>({ current: FALLBACK });

let loading: Promise<Brand> | null = null;

export function loadBrand(): Promise<Brand> {
  loading ??= getBrand()
    .then((loaded) => {
      setBrand(loaded);
      return loaded;
    })
    .catch(() => FALLBACK);
  return loading;
}

export function setBrand(next: Brand) {
  brand.current = next;
  setFavicon(next);
}

// The logo, or the icon emoji drawn in an SVG
function setFavicon(next: Brand) {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.append(link);
  }
  const icon = next.icon || next.name.charAt(0).toUpperCase();
  link.href =
    logoUrl(next) ??
    "data:image/svg+xml," +
      encodeURIComponent(
        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">` +
          `<text y=".9em" font-size="90">${escapeXml(icon)}</text></svg>`,
      );
}

function escapeXml(text: string): string {
  return text.replace(/[<>&"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
