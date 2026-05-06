import { View, Text, TouchableOpacity, StyleSheet, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAuth } from '@/contexts/auth';
import { Colors } from '@/constants/theme';

export default function Settings() {
  const { user, signOut } = useAuth();

  const handleSignOut = () => {
    Alert.alert('Sign Out', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Sign Out', style: 'destructive', onPress: signOut },
    ]);
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Settings</Text>
      </View>

      <View style={styles.section}>
        <View style={styles.card}>
          <Text style={styles.label}>Account</Text>
          <Text style={styles.value}>{user?.email}</Text>
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>Plan</Text>
          <View style={styles.planBadge}>
            <Text style={styles.planText}>Free</Text>
          </View>
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>Bot Status</Text>
          <View style={[styles.statusDot, { backgroundColor: Colors.green }]} />
          <Text style={[styles.value, { color: Colors.green }]}>Active</Text>
        </View>
      </View>

      <View style={styles.section}>
        <TouchableOpacity style={styles.signOutButton} onPress={handleSignOut}>
          <Text style={styles.signOutText}>Sign Out</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.cream },
  header: {
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 20,
  },
  headerTitle: { fontSize: 22, fontWeight: '300', color: Colors.dark },
  section: { paddingHorizontal: 16, marginBottom: 20 },
  card: {
    backgroundColor: Colors.white,
    borderRadius: 12,
    padding: 16,
    marginBottom: 8,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  label: { fontSize: 14, fontWeight: '500', color: Colors.dark },
  value: { fontSize: 14, color: Colors.textLight },
  planBadge: {
    backgroundColor: Colors.olive,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 50,
  },
  planText: { color: Colors.gold, fontSize: 12, fontWeight: '600' },
  statusDot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },
  signOutButton: {
    backgroundColor: Colors.white,
    borderRadius: 12,
    padding: 16,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.red,
  },
  signOutText: { color: Colors.red, fontSize: 15, fontWeight: '500' },
});
