import "./app.css";
import Logout from "./lib/desk/Logout.svelte";
import { mount } from "svelte";

const app = mount(Logout, {
  target: document.getElementById("app")!,
});

export default app;
