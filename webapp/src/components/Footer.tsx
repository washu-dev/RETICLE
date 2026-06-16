import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { FONT_SANS } from "../theme/typography";

export default function Footer() {
  return (
    <View style={styles.container} accessibilityRole="contentinfo">
      <Text style={styles.text}>
        © 2024 Washington University in St. Louis. All rights reserved.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    width: "100%",
    paddingVertical: 12,
    paddingHorizontal: 24,
    alignItems: "center",
    borderTopWidth: 1,
    borderTopColor: "#E0E0E0",
  },
  text: {
    fontFamily: FONT_SANS,
    fontSize: 12,
    color: "#757575",
    textAlign: "center",
  },
});
