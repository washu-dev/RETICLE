import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { useGreeting } from "../hooks/useGreeting";
import LoadingIndicator from "./LoadingIndicator";
import ErrorMessage from "./ErrorMessage";
import { FONT_SERIF } from "../theme/typography";

export default function GreetingScreen() {
  const { status, message, error, retry } = useGreeting();

  if (status === "idle" || status === "loading") {
    return <LoadingIndicator />;
  }

  if (status === "error") {
    return (
      <ErrorMessage
        message={error ?? "Something went wrong."}
        onRetry={retry}
      />
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.greeting}>{message}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 32,
    alignItems: "center",
    justifyContent: "center",
  },
  greeting: {
    fontFamily: FONT_SERIF,
    fontSize: 32,
    color: "#212121",
    textAlign: "center",
  },
});
