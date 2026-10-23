import "./app.css";
import Login from "./lib/desk/Login.svelte";
import { mount } from "svelte";

const app = mount(Login, {
  target: document.getElementById("app")!,
});

export default app;
