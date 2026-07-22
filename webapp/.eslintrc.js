module.exports = {
  parser: "@typescript-eslint/parser",
  plugins: ["@typescript-eslint"],
  extends: ["eslint:recommended", "plugin:@typescript-eslint/recommended"],
  env: { browser: true, es2020: true, node: true },
  rules: { "@typescript-eslint/no-explicit-any": "warn" },
};
