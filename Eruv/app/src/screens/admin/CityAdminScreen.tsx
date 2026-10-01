// One city's admin page: launch offset / break tolerance (R27), poles (R26),
// device key create or rotate (R25), and setting the reference (R27, AE10).
import { useFocusEffect, useNavigation, useRoute, type NavigationProp, type RouteProp } from '@react-navigation/native';
import { useCallback, useState } from 'react';
import { ActivityIndicator, Text } from 'react-native';

import { api, ApiError, errorCode, type AdminCity } from '../../api/client';
import { Button, ErrorText, Field, Screen } from '../../components/ui';
import { he } from '../../i18n/he';
import { formatNumber } from '../../lib/format';
import { formatDateTime } from '../../lib/time';
import type { AdminStackParams } from '../../navigation/types';
import { adminStyles, confirmAction, Section } from './common';

type Nav = NavigationProp<AdminStackParams>;

function parseMeters(text: string): number | null {
  const value = Number(text.trim());
  return text.trim() !== '' && Number.isFinite(value) && value >= 0 ? value : null;
}

interface ConfirmRequired {
  fiber_length_m: number;
  perimeter_m: number;
  shortfall_pct: number;
}

export function CityAdminScreen() {
  const navigation = useNavigation<Nav>();
  const { cityId } = useRoute<RouteProp<AdminStackParams, 'AdminCity'>>().params;
  const [city, setCity] = useState<AdminCity | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [offset, setOffset] = useState('');
  const [tolerance, setTolerance] = useState('');
  const [settingsMsg, setSettingsMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [savingSettings, setSavingSettings] = useState(false);

  const [deviceError, setDeviceError] = useState<string | null>(null);
  const [deviceBusy, setDeviceBusy] = useState(false);
  const [referenceMsg, setReferenceMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [referenceBusy, setReferenceBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const found = (await api.adminCities()).find((c) => c.id === cityId) ?? null;
      setCity(found);
      setLoadError(found ? null : he.admin.city.notFound);
      if (found) {
        setOffset(String(found.launch_offset_m));
        setTolerance(String(found.break_tolerance_m));
      }
    } catch {
      setLoadError(he.admin.cities.loadError);
    }
  }, [cityId]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  async function saveSettings() {
    const launch_offset_m = parseMeters(offset);
    const break_tolerance_m = parseMeters(tolerance);
    if (launch_offset_m === null || break_tolerance_m === null) {
      setSettingsMsg({ ok: false, text: he.admin.cities.invalidNumber });
      return;
    }
    setSavingSettings(true);
    try {
      setCity(await api.adminUpdateCity(cityId, { launch_offset_m, break_tolerance_m }));
      setSettingsMsg({ ok: true, text: he.admin.saved });
    } catch {
      setSettingsMsg({ ok: false, text: he.common.genericError });
    } finally {
      setSavingSettings(false);
    }
  }

  async function issueKey() {
    if (!city) return;
    setDeviceBusy(true);
    setDeviceError(null);
    try {
      const key = await api.adminDeviceKey(cityId);
      navigation.navigate('DeviceKey', { cityName: city.name, deviceId: key.device_id, apiKey: key.api_key });
    } catch {
      setDeviceError(he.common.genericError);
    } finally {
      setDeviceBusy(false);
    }
  }

  function onDeviceKey() {
    if (city?.has_device) confirmAction(he.admin.city.confirmRotate, () => void issueKey());
    else void issueKey();
  }

  async function submitReference(confirmShort: boolean) {
    setReferenceBusy(true);
    setReferenceMsg(null);
    try {
      const result = await api.adminSetReference(cityId, confirmShort);
      setReferenceMsg({ ok: true, text: he.admin.city.referenceSet(formatNumber(result.reference_fiber_length_m)) });
      void load();
    } catch (err) {
      const code = errorCode(err);
      if (code === 'break_active') setReferenceMsg({ ok: false, text: he.admin.city.breakActive });
      else if (code === 'no_valid_result') setReferenceMsg({ ok: false, text: he.admin.city.noValidResult });
      else if (code === 'confirm_required' && err instanceof ApiError) {
        const d = err.detail as ConfirmRequired;
        confirmAction(
          he.admin.city.confirmShort(formatNumber(d.fiber_length_m), formatNumber(d.perimeter_m), formatNumber(d.shortfall_pct)),
          () => void submitReference(true),
          he.admin.city.confirmShortTitle,
        );
      } else setReferenceMsg({ ok: false, text: he.common.genericError });
    } finally {
      setReferenceBusy(false);
    }
  }

  function onSetReference() {
    if (city?.reference_fiber_length_m != null) {
      confirmAction(he.admin.city.confirmRebaseline, () => void submitReference(false));
    } else void submitReference(false);
  }

  if (!city) {
    return <Screen>{loadError ? <ErrorText>{loadError}</ErrorText> : <ActivityIndicator />}</Screen>;
  }

  return (
    <Screen>
      <Section title={he.admin.city.settings}>
        <Text style={adminStyles.note}>{he.admin.cities.launchOffset}</Text>
        <Field testID="city-launch-offset" keyboardType="decimal-pad" value={offset} onChangeText={setOffset} />
        <Text style={adminStyles.note}>{he.admin.cities.breakTolerance}</Text>
        <Field testID="city-break-tolerance" keyboardType="decimal-pad" value={tolerance} onChangeText={setTolerance} />
        {settingsMsg ? (
          <Text style={settingsMsg.ok ? adminStyles.success : adminStyles.error}>{settingsMsg.text}</Text>
        ) : null}
        <Button testID="save-city-settings" title={he.admin.save} busy={savingSettings} onPress={() => void saveSettings()} />
      </Section>

      <Section title={he.admin.city.poles}>
        <Text style={adminStyles.note}>
          {city.pole_count > 0 && city.perimeter_m !== null
            ? he.admin.city.poleSummary(city.pole_count, formatNumber(city.perimeter_m))
            : he.admin.city.noPoles}
        </Text>
        <Button
          testID="import-poles"
          title={he.admin.city.importPoles}
          onPress={() => navigation.navigate('PoleImport', { cityId, cityName: city.name })}
        />
      </Section>

      <Section title={he.admin.city.device}>
        <Text style={adminStyles.note}>
          {city.has_device
            ? city.device_key_rotated_at
              ? he.admin.city.keyRotatedAt(formatDateTime(city.device_key_rotated_at))
              : he.admin.cities.hasDevice
            : he.admin.cities.noDevice}
        </Text>
        <ErrorText>{deviceError}</ErrorText>
        <Button
          testID="device-key"
          title={city.has_device ? he.admin.city.rotateKey : he.admin.city.createDevice}
          busy={deviceBusy}
          onPress={onDeviceKey}
        />
      </Section>

      <Section title={he.admin.city.reference}>
        <Text style={adminStyles.note}>
          {city.reference_fiber_length_m !== null && city.reference_set_at
            ? he.admin.city.referenceValue(formatNumber(city.reference_fiber_length_m), formatDateTime(city.reference_set_at))
            : he.admin.city.noReference}
        </Text>
        {referenceMsg ? (
          <Text testID="reference-message" style={referenceMsg.ok ? adminStyles.success : adminStyles.error}>
            {referenceMsg.text}
          </Text>
        ) : null}
        <Button testID="set-reference" title={he.admin.city.setReference} busy={referenceBusy} onPress={onSetReference} />
      </Section>
    </Screen>
  );
}
