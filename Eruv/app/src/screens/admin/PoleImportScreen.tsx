// Pole import (R26): pick a CSV or KML file, let the server parse it into a preview
// (nothing saved), show it on the ring map with any errors inline, then replace the
// city's poles after confirmation.
import { useNavigation, useRoute, type NavigationProp, type RouteProp } from '@react-navigation/native';
import * as DocumentPicker from 'expo-document-picker';
import { useState } from 'react';
import { ActivityIndicator, Alert, ScrollView, StyleSheet, Text, View } from 'react-native';

import { api, ApiError, errorCode, type PoleImportError, type PolePreview } from '../../api/client';
import { EruvMap } from '../../components/EruvMap';
import { Button, colors, ErrorText } from '../../components/ui';
import { he } from '../../i18n/he';
import { formatNumber } from '../../lib/format';
import type { AdminStackParams } from '../../navigation/types';
import { adminStyles, confirmAction } from './common';

/** The server's per-row errors from a 422 invalid_poles, else null. */
function importErrors(err: unknown): PoleImportError[] | null {
  if (!(err instanceof ApiError) || err.status !== 422 || errorCode(err) !== 'invalid_poles') return null;
  const errors = (err.detail as { errors?: PoleImportError[] }).errors;
  return Array.isArray(errors) ? errors : null;
}

function errorLine(e: PoleImportError): string {
  if (e.missing_number !== null && e.missing_number !== undefined) return he.admin.poles.missingNumber(e.missing_number);
  if (e.row !== null && e.row !== undefined) return he.admin.poles.rowError(e.row, e.message);
  return e.message;
}

export function PoleImportScreen() {
  const navigation = useNavigation<NavigationProp<AdminStackParams>>();
  const { cityId, cityName } = useRoute<RouteProp<AdminStackParams, 'PoleImport'>>().params;
  const [fileName, setFileName] = useState<string | null>(null);
  const [preview, setPreview] = useState<PolePreview | null>(null);
  const [errors, setErrors] = useState<PoleImportError[] | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);

  function showFailure(err: unknown) {
    const rows = importErrors(err);
    setErrors(rows);
    setFailure(rows ? null : he.common.genericError);
  }

  async function pick() {
    // '*/*': Android rarely knows a MIME type for .kml; the server validates the content.
    const picked = await DocumentPicker.getDocumentAsync({ type: '*/*', copyToCacheDirectory: true, multiple: false });
    if (picked.canceled || !picked.assets?.length) return;
    const asset = picked.assets[0];
    setFileName(asset.name);
    setPreview(null);
    setErrors(null);
    setFailure(null);
    setUploading(true);
    try {
      setPreview(await api.adminPreviewPoles(cityId, { uri: asset.uri, name: asset.name, mimeType: asset.mimeType }));
    } catch (err) {
      showFailure(err);
    } finally {
      setUploading(false);
    }
  }

  function save() {
    if (!preview) return;
    confirmAction(he.admin.poles.confirmReplace(preview.count, cityName), async () => {
      setSaving(true);
      try {
        const saved = await api.adminReplacePoles(cityId, preview.poles);
        Alert.alert(he.admin.saved, he.admin.poles.savedMessage(saved.count));
        navigation.goBack();
      } catch (err) {
        showFailure(err);
        setPreview(null);
      } finally {
        setSaving(false);
      }
    });
  }

  return (
    <View style={styles.container}>
      <View style={styles.top}>
        <Text style={adminStyles.note}>{he.admin.poles.explain}</Text>
        <Button testID="pick-pole-file" title={he.admin.poles.pick} busy={uploading} onPress={() => void pick()} />
        {fileName ? <Text style={adminStyles.note}>{he.admin.poles.file(fileName)}</Text> : null}
        {preview ? (
          <Text testID="pole-preview-summary" style={adminStyles.cardTitle}>
            {he.admin.poles.previewSummary(preview.count, formatNumber(preview.perimeter_m))}
          </Text>
        ) : null}
        <ErrorText>{failure}</ErrorText>
      </View>
      {errors ? (
        <ScrollView testID="pole-errors" contentContainerStyle={styles.errors}>
          <ErrorText>{he.admin.poles.errorsTitle}</ErrorText>
          {errors.map((e, i) => (
            <ErrorText key={i}>{errorLine(e)}</ErrorText>
          ))}
        </ScrollView>
      ) : null}
      {uploading ? <ActivityIndicator style={styles.spinner} /> : null}
      {preview ? (
        <>
          <View style={styles.map}>
            <EruvMap poles={preview.poles} breakPoint={null} testID="pole-preview-map" />
          </View>
          <View style={styles.bottom}>
            <Button testID="save-poles" title={he.admin.poles.save} busy={saving} onPress={save} />
          </View>
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  top: { padding: 16, gap: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  errors: { padding: 16, gap: 4 },
  spinner: { padding: 16 },
  map: { flex: 1 },
  bottom: { padding: 16 },
});
