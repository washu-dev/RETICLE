import React from "react";
import { View, StyleSheet } from "react-native";
import Header from "./components/Header";
import Footer from "./components/Footer";
import GreetingScreen from "./components/GreetingScreen";

export default function App() {
  return (
    <View style={styles.container}>
      <Header />
      <View style={styles.main} accessibilityRole="main">
        <GreetingScreen />
      </View>
      <Footer />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    minHeight: "100vh" as unknown as number,
    flexDirection: "column",
  },
  main: {
    flex: 1,
  },
});
