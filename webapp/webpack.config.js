const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const webpack = require("webpack");

module.exports = {
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
    extensions: [".web.tsx", ".web.ts", ".web.js", ".tsx", ".ts", ".js"],
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
    ],
  },
  plugins: [
    new HtmlWebpackPlugin({
      template: "./public/index.html",
    }),
    new webpack.DefinePlugin({
      "process.env.REACT_APP_API_BASE_URL": JSON.stringify(
        process.env.REACT_APP_API_BASE_URL || "http://localhost:8000"
      ),
    }),
  ],
  devServer: {
    port: 3001,
    hot: true,
    open: true,
  },
};
