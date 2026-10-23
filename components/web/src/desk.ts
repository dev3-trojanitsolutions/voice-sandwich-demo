import "./app.css";
import Desk from "./lib/desk/Desk.svelte";
import { mount } from "svelte";

const app = mount(Desk, {
  target: document.getElementById("app")!,
});

export default app;
