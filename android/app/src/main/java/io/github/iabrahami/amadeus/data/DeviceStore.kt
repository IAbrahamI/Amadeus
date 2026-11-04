package io.github.iabrahami.amadeus.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * The pairing: your PC's Tailscale name and this phone's device key. Stored encrypted with the Android Keystore,
 * never in backups (see data_extraction_rules.xml). "Unpair" deletes both. Also the app's own small settings.
 */
class DeviceStore(context: Context) {
    private val prefs = EncryptedSharedPreferences.create(
        context, "amadeus_device",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var host: String?
        get() = prefs.getString("host", null)
        set(v) = prefs.edit().putString("host", v).apply()

    var deviceKey: String?
        get() = prefs.getString("key", null)
        set(v) = prefs.edit().putString("key", v).apply()

    val paired: Boolean get() = !host.isNullOrBlank() && !deviceKey.isNullOrBlank()

    /** The assistant's name, avatar sprite set ("" = the default icon), from the PC's settings. */
    var assistantName: String
        get() = prefs.getString("name", null) ?: "Amadeus"
        set(v) = prefs.edit().putString("name", v).apply()
    var avatarSet: String
        get() = prefs.getString("avatar", "") ?: ""
        set(v) = prefs.edit().putString("avatar", v).apply()

    /** "Calls on this phone": keep the live link to the PC open and ring for its calls. */
    var calls: Boolean
        get() = prefs.getBoolean("calls", true)
        set(v) = prefs.edit().putBoolean("calls", v).apply()

    /** Events already shown as a call, so a reconnect doesn't ring twice (the last 200). */
    fun alreadyShown(id: String): Boolean {
        val seen = prefs.getString("shown", "")!!.split(',').filter { it.isNotBlank() }
        if (id in seen) return true
        prefs.edit().putString("shown", (seen + id).takeLast(200).joinToString(",")).apply()
        return false
    }

    fun unpair() = prefs.edit().clear().apply()
}
