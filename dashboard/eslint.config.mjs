import nextConfig from "eslint-config-next";

const eslintConfig = [
  ...nextConfig,
  {
    rules: {
      // This rule targets the React Compiler's preferred patterns (derive state
      // during render, or resync via a `key` remount) rather than a correctness
      // bug. The prop-to-draft-state resync effects it flags here (Settings,
      // Pipeline, Combobox) are a working, previously-audited pattern; rewriting
      // them is a real refactor, not a lint fix, and out of scope for this pass.
      "react-hooks/set-state-in-effect": "off",
    },
  },
];

export default eslintConfig;
