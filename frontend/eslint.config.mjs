import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

export default [
  { ignores: [".next/**", ".next-demo/**", "node_modules/**"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];
