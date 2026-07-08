// Ambient type for CSS Module imports, so the library dts build can emit declarations
// for components that import `*.module.css` (mirrors vite/client's own declaration).
declare module "*.module.css" {
  const classes: { readonly [key: string]: string };
  export default classes;
}

// Side-effect import of a plain stylesheet (design tokens).
declare module "*.css";
