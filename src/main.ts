console.time("[⏱ 前端启动]");
import { createApp } from "vue";
import App from "./App.vue";

createApp(App).mount("#app");
console.timeEnd("[⏱ 前端启动]");