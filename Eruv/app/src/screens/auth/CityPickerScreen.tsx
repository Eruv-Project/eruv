// City choice: the list component used inside registration, and the screen a
// maintainer reaches from Settings to request another city (R22, back to approval).
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Body, Button, colors, ErrorText, Screen, Title } from '../../components/ui';
import { useCities } from '../../components/useCities';
import { he } from '../../i18n/he';
import type { RootStackParams } from '../../navigation/types';
import { useAuthStore } from '../../state/auth';
import { authErrorMessage } from './errors';

export function CityPicker({
  selectedId,
  onSelect,
  excludeId,
}: {
  selectedId: number | null;
  onSelect: (id: number) => void;
  excludeId?: number | null;
}) {
  const { cities, error, reload } = useCities();
  if (error) {
    return (
      <View>
        <ErrorText>{he.cityPicker.loadError}</ErrorText>
        <Button variant="link" title={he.common.retry} onPress={() => void reload()} />
      </View>
    );
  }
  if (!cities) return <Body>{he.common.loading}</Body>;
  const shown = cities.filter((c) => c.id !== excludeId);
  if (shown.length === 0) return <Body>{he.cityPicker.empty}</Body>;
  return (
    <View style={styles.list} accessibilityRole="radiogroup">
      {shown.map((city) => {
        const selected = city.id === selectedId;
        return (
          <Pressable
            key={city.id}
            testID={`city-option-${city.id}`}
            accessibilityRole="radio"
            accessibilityState={{ selected }}
            onPress={() => onSelect(city.id)}
            style={[styles.option, selected && styles.selected]}
          >
            <Text style={styles.optionText}>{city.name}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function CityChangeScreen(_props: NativeStackScreenProps<RootStackParams, 'CityChange'>) {
  const approvedCityId = useAuthStore((s) => s.user?.approved_city_id ?? null);
  const requestCityChange = useAuthStore((s) => s.requestCityChange);
  const [cityId, setCityId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (cityId === null) return;
    setBusy(true);
    setError(null);
    try {
      await requestCityChange(cityId); // phase -> pending; the navigator swaps to the pending screen
    } catch (err) {
      setError(authErrorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Title>{he.cityPicker.changeTitle}</Title>
      <Body>{he.cityPicker.changeExplain}</Body>
      <CityPicker selectedId={cityId} onSelect={setCityId} excludeId={approvedCityId} />
      <ErrorText>{error}</ErrorText>
      {cityId !== null ? (
        <Button title={he.cityPicker.submitChange} onPress={() => void submit()} busy={busy} />
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  list: { gap: 8 },
  option: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12 },
  selected: { backgroundColor: colors.selected, borderColor: colors.primary },
  optionText: { fontSize: 16, color: colors.text, textAlign: 'left' },
});
