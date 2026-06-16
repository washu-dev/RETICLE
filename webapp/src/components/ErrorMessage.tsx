import React from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { FONT_SANS } from "../theme/typography";

interface ErrorMessageProps {
  message: string;
  onRetry: () => void;
}

export default function ErrorMessage({ message, onRetry }: ErrorMessageProps) {
  return (
    <View style={styles.container} accessibilityRole="alert">
      <Text style={styles.message}>{message}</Text>
      <Pressable
        style={styles.retryButton}
        onPress={onRetry}
        accessibilityRole="button"
        accessibilityLabel="Retry"
      >
        <Text style={styles.retryText}>Retry</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 24,
    alignItems: "center",
    gap: 12,
  },
  message: {
    fontFamily: FONT_SANS,
    fontSize: 15,
    color: "#B71C1C",
    textAlign: "center",
  },
  retryButton: {
    backgroundColor: "#A51417",
    paddingVertical: 8,
    paddingHorizontal: 20,
    borderRadius: 4,
  },
  retryText: {
    fontFamily: FONT_SANS,
    fontSize: 14,
    color: "#FFFFFF",
    fontWeight: "600",
  },
});
