// Admin home (R24, R25): the pending registration queue, approved users, and the cities.
import { useFocusEffect, useNavigation, type NavigationProp } from '@react-navigation/native';
import { useCallback, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { api, ApiError, type AdminCity, type AdminUser, type UserAction } from '../../api/client';
import { Button, ErrorText, Field, Screen } from '../../components/ui';
import { he } from '../../i18n/he';
import type { AdminStackParams } from '../../navigation/types';
import { useAuthStore } from '../../state/auth';
import { ActionButton, adminStyles, confirmAction, Section } from './common';

type Nav = NavigationProp<AdminStackParams>;

export function AdminHomeScreen() {
  const navigation = useNavigation<Nav>();
  const me = useAuthStore((s) => s.user);
  const [pending, setPending] = useState<AdminUser[] | null>(null);
  const [approved, setApproved] = useState<AdminUser[] | null>(null);
  const [cities, setCities] = useState<AdminCity[] | null>(null);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [citiesError, setCitiesError] = useState<string | null>(null);
  const [newCity, setNewCity] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const loadUsers = useCallback(async () => {
    try {
      const [p, a] = await Promise.all([api.adminUsers('pending'), api.adminUsers('approved')]);
      setPending(p);
      setApproved(a);
      setUsersError(null);
    } catch {
      setUsersError(he.admin.users.loadError);
    }
  }, []);

  const loadCities = useCallback(async () => {
    try {
      setCities(await api.adminCities());
      setCitiesError(null);
    } catch {
      setCitiesError(he.admin.cities.loadError);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void loadUsers();
      void loadCities();
    }, [loadUsers, loadCities]),
  );

  const cityName = (id: number | null) => cities?.find((c) => c.id === id)?.name ?? '—';

  function runAction(target: AdminUser, action: UserAction) {
    const messages: Record<UserAction, string> = {
      approve: he.admin.users.confirmApprove(target.name, cityName(target.requested_city_id)),
      reject: he.admin.users.confirmReject(target.name),
      disable: he.admin.users.confirmDisable(target.name),
      promote: he.admin.users.confirmPromote(target.name),
    };
    confirmAction(messages[action], async () => {
      try {
        await api.adminUserAction(target.id, action);
        setUsersError(null);
      } catch (err) {
        setUsersError(err instanceof ApiError && err.status === 409 ? he.admin.users.self : he.common.genericError);
      }
      await loadUsers();
    });
  }

  async function createCity() {
    const name = newCity.trim();
    if (!name) {
      setCreateError(he.admin.cities.nameRequired);
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      const city = await api.adminCreateCity({ name });
      setNewCity('');
      await loadCities();
      navigation.navigate('AdminCity', { cityId: city.id, cityName: city.name });
    } catch {
      setCreateError(he.common.genericError);
    } finally {
      setCreating(false);
    }
  }

  return (
    <Screen>
      <ErrorText>{usersError}</ErrorText>
      <Section title={he.admin.users.pending}>
        {pending?.length === 0 ? <Text style={adminStyles.note}>{he.admin.users.noPending}</Text> : null}
        {pending?.map((u) => (
          <View key={u.id} testID={`user-${u.id}`} style={adminStyles.card}>
            <Text style={adminStyles.cardTitle}>{u.name}</Text>
            <Text style={adminStyles.cardLine}>{`${u.email} · ${u.phone}`}</Text>
            <Text style={adminStyles.cardLine}>{he.admin.users.requestedCity(cityName(u.requested_city_id))}</Text>
            <View style={adminStyles.actions}>
              <ActionButton testID={`user-${u.id}-approve`} title={he.admin.users.approve} onPress={() => runAction(u, 'approve')} />
              <ActionButton
                testID={`user-${u.id}-reject`}
                tone="danger"
                title={he.admin.users.reject}
                onPress={() => runAction(u, 'reject')}
              />
            </View>
          </View>
        ))}
      </Section>

      <Section title={he.admin.users.approved}>
        {approved?.length === 0 ? <Text style={adminStyles.note}>{he.admin.users.noUsers}</Text> : null}
        {approved?.map((u) => {
          const self = u.id === me?.id;
          return (
            <View key={u.id} testID={`user-${u.id}`} style={adminStyles.card}>
              <Text style={adminStyles.cardTitle}>{self ? `${u.name} ${he.admin.users.you}` : u.name}</Text>
              <Text style={adminStyles.cardLine}>{`${u.email} · ${u.phone}`}</Text>
              <Text style={adminStyles.cardLine}>
                {u.role === 'admin' ? he.admin.users.adminRole : he.admin.users.city(cityName(u.approved_city_id))}
              </Text>
              {self ? null : (
                <View style={adminStyles.actions}>
                  {u.role === 'admin' ? null : (
                    <ActionButton
                      testID={`user-${u.id}-promote`}
                      title={he.admin.users.promote}
                      onPress={() => runAction(u, 'promote')}
                    />
                  )}
                  <ActionButton
                    testID={`user-${u.id}-disable`}
                    tone="danger"
                    title={he.admin.users.disable}
                    onPress={() => runAction(u, 'disable')}
                  />
                </View>
              )}
            </View>
          );
        })}
      </Section>

      <Section title={he.admin.cities.title}>
        <ErrorText>{citiesError}</ErrorText>
        {cities?.length === 0 ? <Text style={adminStyles.note}>{he.admin.cities.empty}</Text> : null}
        {cities?.map((c) => (
          <Pressable
            key={c.id}
            testID={`city-${c.id}`}
            accessibilityRole="button"
            onPress={() => navigation.navigate('AdminCity', { cityId: c.id, cityName: c.name })}
            style={adminStyles.card}
          >
            <Text style={adminStyles.cardTitle}>{c.name}</Text>
            <Text style={adminStyles.cardLine}>
              {he.admin.cities.summary(c.pole_count, c.has_device ? he.admin.cities.hasDevice : he.admin.cities.noDevice)}
            </Text>
            <Text style={adminStyles.cardLine}>
              {`${he.logs.states[c.line_state] ?? c.line_state} · ${he.logs.states[c.device_health] ?? c.device_health}`}
            </Text>
          </Pressable>
        ))}
        <Field testID="new-city-name" placeholder={he.admin.cities.name} value={newCity} onChangeText={setNewCity} />
        <ErrorText>{createError}</ErrorText>
        <Button testID="create-city" title={he.admin.cities.create} busy={creating} onPress={() => void createCity()} />
      </Section>
    </Screen>
  );
}
