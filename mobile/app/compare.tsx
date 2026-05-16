import { useRouter } from 'expo-router';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import { Colors } from '@/constants/theme';

const API_BASE = 'https://bot.lumitrade.ai';

export default function CompareScreen() {
  const router = useRouter();
  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
          <Text style={styles.backText}>Back</Text>
        </TouchableOpacity>
        <View style={styles.titleBlock}>
          <Text style={styles.title}>SNR Compare</Text>
          <Text style={styles.subtitle}>TV vs Server vs LumiTrade</Text>
        </View>
        <View style={{ width: 60 }} />
      </View>
      <WebView
        source={{ uri: `${API_BASE}/mobile_compare` }}
        style={styles.webview}
        javaScriptEnabled
        domStorageEnabled
        startInLoadingState
        renderLoading={() => (
          <ActivityIndicator style={{ flex: 1, backgroundColor: Colors.cream }} color={Colors.olive} />
        )}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 8,
    backgroundColor: Colors.cream,
    gap: 10,
  },
  backBtn: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    backgroundColor: '#e5e3dd',
  },
  backText: { color: Colors.dark, fontSize: 14 },
  titleBlock: { flex: 1, alignItems: 'center' },
  title: { color: Colors.dark, fontSize: 16, fontWeight: '600' },
  subtitle: { color: Colors.textLight, fontSize: 11, marginTop: 1 },
  webview: { flex: 1 },
});
