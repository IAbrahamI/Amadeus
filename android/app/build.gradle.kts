plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "io.github.iabrahami.amadeus"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.iabrahami.amadeus"
        minSdk = 29          // Android 10+
        targetSdk = 35
        val version = rootProject.file("../VERSION").readText().trim()  // one version for everything
        versionCode = version.split(".").fold(0) { code, part -> code * 100 + part.toInt() }
        versionName = version
    }
    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.getByName("debug")  // replaced by your own key (README → Signing)
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true }
    sourceSets["main"].res.srcDir(layout.buildDirectory.dir("generated/logo-res"))
}

// The app icon is your own logo if you put one at core/web/logo-512.png (kept out of git), otherwise the plain
// default logo in core/web/default-logo.png. It is copied in at build time.
val copyLogo by tasks.registering(Copy::class) {
    val own = rootProject.file("../core/web/logo-512.png")
    from(if (own.exists()) own else rootProject.file("../core/web/default-logo.png")) { rename { "amadeus_logo.png" } }
    into(layout.buildDirectory.dir("generated/logo-res/drawable-nodpi"))
}
tasks.named("preBuild") { dependsOn(copyLogo) }

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.androidx.security.crypto)
    implementation(libs.okhttp)
    implementation(libs.okhttp.sse)
    implementation(libs.zxing.embedded)   // QR scanner for pairing (open source, works offline)
}
