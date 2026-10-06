{{- define "dm.labels" -}}
app.kubernetes.io/part-of: digital-mine
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}
{{- define "dm.image" -}}
{{ .root.Values.image.registry }}{{ .name }}:{{ .root.Values.image.tag }}
{{- end }}
