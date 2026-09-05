<script setup lang="ts">
import ModulePlaceholder from '@/components/common/ModulePlaceholder.vue'
import { t } from '@/utils/i18n'
</script>

<template>
  <ModulePlaceholder
    code="MODULE 02 · RESEARCH"
    :title="t('research.title')"
    icon="∇"
    accent="#ff4dd2"
    :description="t('research.desc')"
    :status="t('research.status')"
    :features="[t('research.f1'), t('research.f2'), t('research.f3'), t('research.f4'), t('research.f5'), t('research.f6')]"
  />
</template>
