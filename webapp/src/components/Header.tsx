import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { FONT_SERIF } from "../theme/typography";

export default function Header() {
  return (
    <View style={styles.container} accessibilityRole="banner">
      <Text style={styles.title}>RETICLE</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    width: "100%",
    backgroundColor: "#A51417",
    paddingVertical: 16,
    paddingHorizontal: 24,
  },
  title: {
    fontFamily: FONT_SERIF,
    fontSize: 28,
    fontWeight: "700",
    color: "#FFFFFF",
    letterSpacing: 2,
  },
});
