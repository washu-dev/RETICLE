import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { FONT_SANS } from "../theme/typography";

export default function LoadingIndicator() {
  return (
    <View
      style={styles.container}
      accessibilityRole="alert"
      accessibilityLiveRegion="polite"
      aria-busy="true"
    >
      <Text style={styles.text}>Loading...</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 24,
    alignItems: "center",
  },
  text: {
    fontFamily: FONT_SANS,
    fontSize: 16,
    color: "#616161",
  },
});
