import type { HTMLAttributes } from "react";

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "iphone-16-max": HTMLAttributes<HTMLElement> & {
        mode?: "light" | "dark";
      };
    }
  }
}
