const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const webpack = require("webpack");

// Load webapp/.env (git-ignored) so REACT_APP_* vars are available at build time,
// CRA-style. Values already in the shell environment take precedence.
require("dotenv").config({ path: path.resolve(__dirname, ".env") });

module.exports = (env, argv) => {
  // Only embed the di2chat widget in the deployed production bundle (issue #45).
  // The widget's authorized domain is the CloudFront origin, so it never renders
  // on localhost anyway — this also keeps the remote loader out of local dev.
  const injectChatWidget = argv.mode === "production";

  return {
    entry: "./src/index.web.tsx",
    output: {
      path: path.resolve(__dirname, "web-build"),
      filename: "static/js/[name].[contenthash].js",
      clean: true,
    },
    resolve: {
      alias: {
        "react-native$": "react-native-web",
      },
      extensions: [".web.tsx", ".web.ts", ".web.js", ".tsx", ".ts", ".jsx", ".js"],
    },
    module: {
      rules: [
        {
          test: /\.(tsx?|jsx?)$/,
          exclude: /node_modules/,
          use: {
            loader: "babel-loader",
          },
        },
        {
          test: /\.css$/,
          use: ["style-loader", "css-loader"],
        },
      ],
    },
    plugins: [
      new HtmlWebpackPlugin({
        template: "./public/index.html",
        templateParameters: {
          injectChatWidget,
        },
      }),
      new webpack.DefinePlugin({
        "process.env.REACT_APP_API_BASE_URL": JSON.stringify(
          process.env.REACT_APP_API_BASE_URL || "http://localhost:8000"
        ),
        // Public (non-secret) Entra SSO identifiers for MSAL.js. When set, the
        // SPA initialises MSAL directly and never calls the backend for config.
        "process.env.REACT_APP_SSO_CLIENT_ID": JSON.stringify(
          process.env.REACT_APP_SSO_CLIENT_ID || ""
        ),
        "process.env.REACT_APP_SSO_TENANT_ID": JSON.stringify(
          process.env.REACT_APP_SSO_TENANT_ID || ""
        ),
        // Optional overrides; sensible defaults are derived at runtime.
        "process.env.REACT_APP_SSO_AUTHORITY": JSON.stringify(
          process.env.REACT_APP_SSO_AUTHORITY || ""
        ),
        "process.env.REACT_APP_SSO_REDIRECT_URI": JSON.stringify(
          process.env.REACT_APP_SSO_REDIRECT_URI || ""
        ),
      }),
    ],
    devServer: {
      port: 3001,
      hot: true,
      open: true,
    },
  };
};
